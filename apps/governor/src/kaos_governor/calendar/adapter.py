from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


ALLOWED_PORTAL_HOSTS = {"kaosgdd.net", "family.kaosgdd.net", "supplies.kaosgdd.net"}
ALLOWED_ROUTES = {
    "GET": {"/api/calendar/bootstrap", "/api/weather/month"},
    "POST": {"/api/calendar/events", "/api/calendar/tasks"},
    "PUT": {"/api/calendar/events", "/api/calendar/tasks"},
    "DELETE": {"/api/calendar/events", "/api/calendar/tasks"},
}
PROFILE_HOSTS = {
    "main": "kaosgdd.net",
    "family": "family.kaosgdd.net",
    "supplies": "supplies.kaosgdd.net",
}


class CalendarAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class CalendarAdapterConfig:
    base_url: str
    timeout_seconds: float = 30.0
    user_agent: str = "KaosGovernor/calendar-adapter"

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise CalendarAdapterError("calendar_adapter_base_url_required")
        if self.timeout_seconds <= 0:
            raise CalendarAdapterError("calendar_adapter_timeout_invalid")


def portal_host(headers: Mapping[str, str]) -> str:
    raw = headers.get("X-Forwarded-Host") or headers.get("Host") or "kaosgdd.net"
    host = raw.split(":", 1)[0].lower()
    return host if host in ALLOWED_PORTAL_HOSTS else "kaosgdd.net"


def profile_host(profile: str) -> str:
    try:
        return PROFILE_HOSTS[profile]
    except KeyError as exc:
        raise CalendarAdapterError("calendar_adapter_profile_invalid") from exc


def route_allowed(method: str, path_and_query: str) -> bool:
    parsed = urllib.parse.urlsplit(path_and_query)
    return parsed.path in ALLOWED_ROUTES.get(method.upper(), set())


def upstream_url(base_url: str, method: str, path_and_query: str) -> str:
    parsed = urllib.parse.urlsplit(path_and_query)
    normalized_method = method.upper()
    if not route_allowed(normalized_method, path_and_query):
        raise CalendarAdapterError("calendar_adapter_route_not_allowed")
    return f"{base_url.rstrip('/')}{parsed.path}{'?' + parsed.query if parsed.query else ''}"


class CalendarAdapterClient:
    def __init__(
        self,
        config: CalendarAdapterConfig,
        *,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self._urlopen = urlopen or urllib.request.urlopen

    def bootstrap(self, profile: str) -> dict[str, Any]:
        payload = self.request_json(profile, "GET", "/api/calendar/bootstrap")
        if not payload.get("live"):
            raise CalendarAdapterError("calendar_adapter_unavailable")
        return payload

    def list_tasks(self, profile: str) -> list[dict[str, Any]]:
        payload = self.bootstrap(profile)
        return [dict(item) for item in payload.get("tasks", []) if isinstance(item, Mapping)]

    def month_weather(
        self,
        profile: str,
        *,
        start: str,
        end: str,
        city: str = "pohang",
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode({"city": city, "start": start, "end": end})
        return self.request_json(profile, "GET", f"/api/weather/month?{query}")

    def create_task(self, profile: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = self.request_json(profile, "POST", "/api/calendar/tasks", payload=payload)
        uid = str(result.get("uid") or "").strip()
        if not uid:
            raise CalendarAdapterError("calendar_adapter_missing_uid")
        return result

    def update_task(self, profile: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = self.request_json(profile, "PUT", "/api/calendar/tasks", payload=payload)
        uid = str(result.get("uid") or "").strip()
        if not uid:
            raise CalendarAdapterError("calendar_adapter_missing_uid")
        return result

    def delete_task(self, profile: str, uid: str, collection_id: str) -> dict[str, Any]:
        return self.request_json(
            profile,
            "DELETE",
            "/api/calendar/tasks",
            payload={"uid": uid, "collectionId": collection_id},
        )

    def health(self, profile: str) -> dict[str, Any]:
        host = profile_host(profile)
        started = time.monotonic()
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/health",
            headers=self._headers(host),
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = _decode_json(response.read())
            return {
                "ok": response.status == 200 and bool(payload.get("ok")),
                "status": response.status,
                "profile": payload.get("profile", ""),
                "configured": bool(payload.get("configured")),
                "latencyMs": round((time.monotonic() - started) * 1000, 1),
            }
        except (CalendarAdapterError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return {
                "ok": False,
                "error": type(exc).__name__,
                "latencyMs": round((time.monotonic() - started) * 1000, 1),
            }

    def request_json(
        self,
        profile: str,
        method: str,
        path_and_query: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, response_body = self.request(profile, method, path_and_query, body=body)
        decoded = _decode_json(response_body)
        if status < 200 or status >= 300:
            raise CalendarAdapterError(str(decoded.get("error") or f"calendar_adapter_http_{status}"))
        return decoded

    def request(
        self,
        profile: str,
        method: str,
        path_and_query: str,
        *,
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, bytes]:
        host = profile_host(profile)
        normalized_method = method.upper()
        request = urllib.request.Request(
            upstream_url(self.config.base_url, normalized_method, path_and_query),
            data=body,
            method=normalized_method,
            headers=self._headers(host),
        )
        if body is not None:
            request.add_header("Content-Type", content_type or "application/json")
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def _headers(self, host: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Host": host,
            "X-Forwarded-Host": host,
            "User-Agent": self.config.user_agent,
        }


def _decode_json(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalendarAdapterError("calendar_adapter_invalid_response") from exc
    if not isinstance(payload, dict):
        raise CalendarAdapterError("calendar_adapter_invalid_response")
    return payload
