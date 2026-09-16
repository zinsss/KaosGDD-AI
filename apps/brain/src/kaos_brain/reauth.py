from __future__ import annotations

from dataclasses import dataclass
import json as jsonlib
import math
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout


class ReauthError(RuntimeError):
    """Raised when the local OpenClaw reauth agent cannot complete a request."""


REAUTH_STATUSES = frozenset(
    {
        "idle",
        "starting",
        "waiting_for_device",
        # Retain the old callback states while H4 deployments transition.
        "waiting_for_callback",
        "submitting",
        "succeeded",
        "failed",
    }
)
REAUTH_URL_PATHS = frozenset({"/codex/device", "/oauth/authorize"})
DEVICE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,62}[A-Z0-9]$")


def _reauth_timestamp(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ReauthError(f"reauth_agent_{name}_invalid")
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ReauthError(f"reauth_agent_{name}_invalid") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ReauthError(f"reauth_agent_{name}_invalid")
    return parsed


def _reauth_verification_url(value: object) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if len(url) > 4096:
        raise ReauthError("reauth_agent_verification_url_invalid")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ReauthError("reauth_agent_verification_url_invalid") from exc
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "auth.openai.com"
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.path not in REAUTH_URL_PATHS
        or parsed.fragment
    ):
        raise ReauthError("reauth_agent_verification_url_invalid")
    return url


def normalize_reauth_payload(value: object) -> dict[str, Any]:
    """Return the small, public-safe subset of an agent response."""

    if not isinstance(value, Mapping):
        raise ReauthError("reauth_agent_payload_invalid")
    status = str(value.get("status") or "").strip().lower()
    if status not in REAUTH_STATUSES:
        raise ReauthError("reauth_agent_status_invalid")
    verification_url = _reauth_verification_url(
        value.get("verificationUrl") or value.get("oauthUrl")
    )
    user_code = str(value.get("userCode") or "").strip().upper()
    if user_code and not DEVICE_CODE_RE.fullmatch(user_code):
        raise ReauthError("reauth_agent_user_code_invalid")
    if status == "waiting_for_device" and (not verification_url or not user_code):
        raise ReauthError("reauth_agent_device_pairing_incomplete")
    payload: dict[str, Any] = {
        "status": status,
        "verificationUrl": verification_url,
        # Keep the older oauthUrl response alias for deployed PWA clients.
        "oauthUrl": verification_url,
        "startedAt": _reauth_timestamp(value.get("startedAt"), "started_at"),
        "completedAt": _reauth_timestamp(value.get("completedAt"), "completed_at"),
    }
    if user_code:
        payload["userCode"] = user_code
    return payload


@dataclass(frozen=True)
class ReauthConfig:
    base_url: str
    api_token: str
    timeout_seconds: int


class OpenClawReauthClient:
    def __init__(self, config: ReauthConfig) -> None:
        self.config = config

    async def start(self) -> dict[str, Any]:
        return await self._request("POST", "/reauth/openai/start")

    async def submit_callback(self, callback_url_or_code: str) -> dict[str, Any]:
        return await self._request("POST", "/reauth/openai/callback", json={"callbackUrl": callback_url_or_code})

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "/reauth/openai/status")

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.config.api_token}"}
        timeout = ClientTimeout(total=self.config.timeout_seconds)
        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    f"{self.config.base_url.rstrip('/')}{path}",
                    headers=headers,
                    json=json,
                ) as response:
                    raw = await response.text()
                    try:
                        payload = jsonlib.loads(raw)
                    except (TypeError, ValueError) as exc:
                        raise ReauthError("reauth_agent_invalid_json") from exc
                    if response.status >= 400:
                        code = (
                            str(payload.get("error") or payload.get("message") or "").strip()
                            if isinstance(payload, Mapping)
                            else ""
                        )
                        if not re.fullmatch(r"[a-z0-9_:-]{1,100}", code):
                            code = f"reauth_agent_http_{response.status}"
                        raise ReauthError(code)
                    return normalize_reauth_payload(payload)
        except (ClientError, TimeoutError) as exc:
            raise ReauthError("reauth_agent_unreachable") from exc
