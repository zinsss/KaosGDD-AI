from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout


class ReauthError(RuntimeError):
    """Raised when the local OpenClaw reauth agent cannot complete a request."""


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
                    payload = await response.json()
                    if response.status >= 400:
                        raise ReauthError(str(payload.get("error") or payload.get("message") or response.status))
                    return payload
        except (ClientError, TimeoutError) as exc:
            raise ReauthError(str(exc)) from exc
