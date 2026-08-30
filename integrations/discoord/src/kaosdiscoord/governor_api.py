from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request


class GovernorApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernorApiConfig:
    base_url: str
    token: str
    timeout_seconds: float = 20.0
    user_agent: str = "KaosGovernor/discord"

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise GovernorApiError("governor_api_base_url_required")
        if not self.token.strip():
            raise GovernorApiError("governor_api_token_required")
        if self.timeout_seconds <= 0:
            raise GovernorApiError("governor_api_timeout_invalid")


class GovernorApiClient:
    def __init__(self, config: GovernorApiConfig) -> None:
        self.config = config

    def sync_recurring_tasks(self, profile: str) -> dict[str, object]:
        host = "family.kaosgdd.net" if profile == "family" else "kaosgdd.net"
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/recurring-tasks/sync",
            data=b"{}",
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "Host": host,
                "X-Forwarded-Host": host,
                "User-Agent": self.config.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GovernorApiError("governor_api_recurring_sync_failed") from exc
        if not isinstance(payload, dict):
            raise GovernorApiError("governor_api_invalid_response")
        if not payload.get("ok"):
            raise GovernorApiError(str(payload.get("error") or "governor_api_recurring_sync_failed"))
        return payload
