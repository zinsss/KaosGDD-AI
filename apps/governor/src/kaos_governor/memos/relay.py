from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping

from kaos_governor.database import connect


PROFILE_BY_HOST = {
    "kaosgdd.net": "personal",
    "family.kaosgdd.net": "family",
}
USERNAME_BY_PROFILE = {
    "personal": "MEMOS_PERSONAL_USERNAME",
    "family": "MEMOS_FAMILY_USERNAME",
}
AUDIENCE_BY_PROFILE = {
    "personal": "CLOUDFLARE_ACCESS_MAIN_AUD",
    "family": "CLOUDFLARE_ACCESS_FAMILY_AUD",
}
ALLOWED_RELAY_ROUTES = {
    "GET": (
        re.compile(r"/api/v1/auth/me"),
        re.compile(r"/api/v1/memos"),
    ),
    "POST": (re.compile(r"/api/v1/memos"),),
    "PATCH": (re.compile(r"/api/v1/memos/[^/]+"),),
    "DELETE": (re.compile(r"/api/v1/memos/[^/]+"),),
}


class MemosRelayError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code


def host(headers: Mapping[str, str]) -> str:
    raw = headers.get("X-Forwarded-Host") or headers.get("Host") or ""
    return raw.split(":", 1)[0].strip().lower()


def profile_for_headers(headers: Mapping[str, str]) -> str:
    profile = PROFILE_BY_HOST.get(host(headers))
    if not profile:
        raise MemosRelayError(404, "memos_relay_profile_not_found")
    return profile


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MemosRelayError(503, "memos_relay_not_configured", f"{name} is not configured")
    return value


def verify_cloudflare_access(headers: Mapping[str, str]) -> tuple[str, str]:
    profile = profile_for_headers(headers)
    assertion = headers.get("Cf-Access-Jwt-Assertion", "").strip()
    if not assertion:
        raise MemosRelayError(401, "cloudflare_access_required")

    team_domain = required_env("CLOUDFLARE_ACCESS_TEAM_DOMAIN").removeprefix("https://").rstrip("/")
    audience = required_env(AUDIENCE_BY_PROFILE[profile])
    try:
        import jwt

        signing_key = jwt.PyJWKClient(
            f"https://{team_domain}/cdn-cgi/access/certs",
            cache_keys=True,
        ).get_signing_key_from_jwt(assertion)
        claims = jwt.decode(
            assertion,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"https://{team_domain}",
            leeway=30,
        )
    except MemosRelayError:
        raise
    except Exception as exc:
        raise MemosRelayError(401, "cloudflare_access_invalid") from exc

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise MemosRelayError(401, "cloudflare_access_identity_missing")
    return profile, email


def fernet():
    try:
        from cryptography.fernet import Fernet

        return Fernet(required_env("MEMOS_RELAY_ENCRYPTION_KEY").encode("ascii"))
    except MemosRelayError:
        raise
    except Exception as exc:
        raise MemosRelayError(503, "memos_relay_encryption_invalid") from exc


def setting_key(profile: str) -> str:
    return f"memos_relay.{profile}.personal_access_token"


def legacy_setting_key(profile: str) -> str:
    return f"{profile}_personal_access_token"


def store_token(profile: str, username: str, token: str) -> None:
    encrypted = fernet().encrypt(token.encode("utf-8")).decode("ascii")
    payload = json.dumps({"username": username, "token": encrypted})
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO governor_settings (settings_key, settings_scope, payload)
            VALUES (%s, 'system', %s::jsonb)
            ON CONFLICT (settings_key) DO UPDATE
            SET payload = EXCLUDED.payload, updated_at = now(), version = governor_settings.version + 1
            """,
            (setting_key(profile), payload),
        )


def _load_governor_setting(profile: str) -> str | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT payload FROM governor_settings WHERE settings_key = %s",
            (setting_key(profile),),
        ).fetchone()
    if not row:
        return None
    value = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return fernet().decrypt(value["token"].encode("ascii")).decode("utf-8")


def _load_legacy_setting(profile: str) -> str | None:
    with connect() as connection:
        exists = connection.execute("SELECT to_regclass('public.brain_settings')").fetchone()
        if not exists or not exists[0]:
            return None
        row = connection.execute(
            "SELECT value FROM brain_settings WHERE scope = 'memos_relay' AND setting_key = %s",
            (legacy_setting_key(profile),),
        ).fetchone()
    if not row:
        return None
    value = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return fernet().decrypt(value["token"].encode("ascii")).decode("utf-8")


def load_token(profile: str) -> str:
    env_name = f"MEMOS_{profile.upper()}_ACCESS_TOKEN"
    env_token = os.environ.get(env_name, "").strip()
    if env_token:
        return env_token
    try:
        token = _load_governor_setting(profile)
        if token:
            return token
        token = _load_legacy_setting(profile)
        if token:
            return token
    except MemosRelayError:
        raise
    except Exception as exc:
        raise MemosRelayError(503, "memos_relay_credential_invalid") from exc
    raise MemosRelayError(503, "memos_relay_profile_not_configured")


def status() -> dict[str, object]:
    result: dict[str, object] = {
        "configured": all(
            os.environ.get(name, "").strip()
            for name in (
                "CLOUDFLARE_ACCESS_TEAM_DOMAIN",
                "CLOUDFLARE_ACCESS_MAIN_AUD",
                "CLOUDFLARE_ACCESS_FAMILY_AUD",
                "MEMOS_RELAY_ENCRYPTION_KEY",
            )
        ),
        "profiles": {},
    }
    profiles: dict[str, object] = {}
    for profile in PROFILE_BY_HOST.values():
        try:
            load_token(profile)
            profiles[profile] = {"configured": True}
        except Exception:
            profiles[profile] = {"configured": False}
    result["profiles"] = profiles
    return result


def upstream_url(path_and_query: str) -> str:
    base = os.environ.get("MEMOS_INTERNAL_URL", "http://memos:5230").rstrip("/")
    return f"{base}{path_and_query}"


def upstream_request(
    method: str,
    path_and_query: str,
    body: bytes | None = None,
    access_token: str = "",
    cookie: str = "",
) -> tuple[int, str, bytes]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "KaosGovernor-Memos-Relay/1.0",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(
        upstream_url(path_and_query),
        data=body,
        method=method,
        headers=headers,
    )
    timeout = float(
        os.environ.get("GOVERNOR_UPSTREAM_TIMEOUT_SECONDS")
        or os.environ.get("BRAIN_UPSTREAM_TIMEOUT_SECONDS")
        or "30"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", "application/json"), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "application/json"), exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MemosRelayError(502, "memos_upstream_unavailable") from exc


def json_body(body: bytes, error_code: str) -> dict[str, object]:
    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MemosRelayError(502, error_code) from exc


def session_access_token(cookie: str) -> str:
    if not cookie:
        raise MemosRelayError(401, "memos_bootstrap_login_required")
    status_code, _, body = upstream_request(
        "POST",
        "/api/v1/auth/refresh",
        body=b"{}",
        cookie=cookie,
    )
    if status_code != 200:
        raise MemosRelayError(401, "memos_bootstrap_login_required")
    access_token = str(json_body(body, "memos_refresh_invalid").get("accessToken") or "")
    if not access_token:
        raise MemosRelayError(502, "memos_refresh_invalid")
    return access_token


def password_access_token(username: str, password: str) -> str:
    body = json.dumps(
        {"passwordCredentials": {"username": username, "password": password}},
        separators=(",", ":"),
    ).encode("utf-8")
    status_code, _, response_body = upstream_request("POST", "/api/v1/auth/signin", body=body)
    if status_code != 200:
        raise MemosRelayError(401, "memos_bootstrap_login_failed")
    access_token = str(json_body(response_body, "memos_signin_invalid").get("accessToken") or "")
    if not access_token:
        raise MemosRelayError(502, "memos_signin_invalid")
    return access_token


def bootstrap(headers: Mapping[str, str], payload: Mapping[str, object]) -> dict[str, object]:
    profile, _ = verify_cloudflare_access(headers)
    expected_username = required_env(USERNAME_BY_PROFILE[profile])
    try:
        token = load_token(profile)
        status_code, _, body = upstream_request("GET", "/api/v1/auth/me", access_token=token)
        if status_code == 200:
            return json_body(body, "memos_current_user_invalid")
    except MemosRelayError as exc:
        if exc.code != "memos_relay_profile_not_configured":
            raise

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if username or password:
        if username != expected_username or not password:
            raise MemosRelayError(403, "memos_bootstrap_profile_mismatch")
        access_token = password_access_token(username, password)
    else:
        access_token = session_access_token(headers.get("Cookie", ""))

    status_code, _, current_body = upstream_request("GET", "/api/v1/auth/me", access_token=access_token)
    if status_code != 200:
        raise MemosRelayError(401, "memos_bootstrap_login_failed")
    current = json_body(current_body, "memos_current_user_invalid")
    user = current.get("user") or {}
    if not isinstance(user, dict) or user.get("name") != f"users/{expected_username}":
        raise MemosRelayError(403, "memos_bootstrap_profile_mismatch")

    pat_body = json.dumps(
        {
            "parent": f"users/{expected_username}",
            "description": f"KaosGovernor {profile} relay",
            "expiresInDays": 0,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    status_code, _, response_body = upstream_request(
        "POST",
        f"/api/v1/users/{urllib.parse.quote(expected_username)}/personalAccessTokens",
        body=pat_body,
        access_token=access_token,
    )
    if status_code != 200:
        raise MemosRelayError(502, "memos_pat_create_failed")
    pat = str(json_body(response_body, "memos_pat_response_invalid").get("token") or "")
    if not pat:
        raise MemosRelayError(502, "memos_pat_response_invalid")
    store_token(profile, expected_username, pat)
    return current


def relay_path(path_and_query: str) -> str:
    parsed = urllib.parse.urlsplit(path_and_query)
    prefix = "/api/memos"
    if parsed.path != prefix and not parsed.path.startswith(f"{prefix}/"):
        raise MemosRelayError(404, "memos_relay_route_not_found")
    path = parsed.path[len(prefix):] or "/"
    return f"{path}{'?' + parsed.query if parsed.query else ''}"


def route_allowed(method: str, path_and_query: str) -> bool:
    parsed = urllib.parse.urlsplit(relay_path(path_and_query))
    return any(pattern.fullmatch(parsed.path) for pattern in ALLOWED_RELAY_ROUTES.get(method, ()))


def relay(
    method: str,
    path_and_query: str,
    headers: Mapping[str, str],
    body: bytes | None = None,
) -> tuple[int, str, bytes]:
    profile, _ = verify_cloudflare_access(headers)
    if not route_allowed(method, path_and_query):
        raise MemosRelayError(404, "memos_relay_route_not_found")
    token = load_token(profile)
    return upstream_request(method, relay_path(path_and_query), body=body, access_token=token)
