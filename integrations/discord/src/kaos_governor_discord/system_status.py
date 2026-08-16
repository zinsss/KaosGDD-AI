from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import socket
import time
from typing import Mapping
import urllib.error
import urllib.request

import discord

from .access import AccessPolicy
from .markdown import NO_MENTIONS


LOGGER = logging.getLogger(__name__)


EMBED_COLOR_HEALTHY = 0xA3BE8C
EMBED_COLOR_DOWN = 0xBF616A
EMBED_COLOR_UNKNOWN = 0x4C566A
MESSAGE_REFRESH_DELAY_SECONDS = 1.25


@dataclass(frozen=True)
class ServiceStatusItem:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class ServiceProbeResult:
    key: str
    state: str
    checked_at: str
    detail: str = ""

    @property
    def healthy(self) -> bool:
        return self.state == "healthy"


@dataclass
class DiscordServiceStatusState:
    message_ids: dict[str, int] | None = None
    legacy_message_id: int = 0
    restart_requests: dict[str, int] | None = None


SERVICES: tuple[ServiceStatusItem, ...] = (
    ServiceStatusItem("kaosbrain", "KaosBrain", "Brain of KaosGDD on Odroid H4 Ultra"),
    ServiceStatusItem("kaosgovernor", "KaosGovernor", "Rules and controller of KaosGDD"),
    ServiceStatusItem("kaospacs", "KaosPACS", "Clinic PACS and DICOM infrastructure"),
    ServiceStatusItem("kaosinj", "KaosInj", "Clinic injection workflow support"),
    ServiceStatusItem("radicale", "Radicale", "Calendar and task source of truth"),
    ServiceStatusItem("memos", "Memos", "Private and family memo source of truth"),
    ServiceStatusItem("paperless", "Paperless", "Document archive and metadata source of truth"),
    ServiceStatusItem("stirlingpdf", "StirlingPDF", "PDF utility service"),
    ServiceStatusItem("vaultwarden", "Vaultwarden", "Password vault service"),
    ServiceStatusItem("rustdesk", "Rustdesk", "Remote support service"),
)

DEFAULT_HTTP_PROBES = {
    "kaosgovernor": "http://127.0.0.1:8097/health",
    "radicale": "http://radicale:5232/",
    "memos": "http://memos:5230/",
    "vaultwarden": "http://vaultwarden/alive",
}

OK_HTTP_STATUSES = {200, 204, 301, 302, 307, 308, 401, 403}


class DiscordServiceStatusSurface:
    def __init__(
        self,
        bot: discord.Client,
        policy: AccessPolicy,
        *,
        channel_id: int,
        state_path: Path,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.bot = bot
        self.policy = policy
        self.channel_id = channel_id
        self.state_path = state_path
        self.state = self._load_state()
        self.environment = os.environ if environment is None else environment
        self.timeout_seconds = service_status_timeout_seconds(self.environment)
        self.refresh_seconds = service_status_refresh_seconds(self.environment)
        self.message_refresh_delay_seconds = MESSAGE_REFRESH_DELAY_SECONDS
        self.last_results: dict[str, ServiceProbeResult] = {}

    async def ensure_message(self) -> None:
        channel = await self.channel()
        results = await self.check_services()
        if self.state.legacy_message_id:
            await self._delete_message_id(channel, self.state.legacy_message_id)
            self.state.legacy_message_id = 0
        next_message_ids: dict[str, int] = {}
        current_message_ids = dict(self.state.message_ids or {})
        for item in SERVICES:
            message = await self._upsert_service_message(
                channel,
                item,
                result=results[item.key],
                message_id=current_message_ids.get(item.key, 0),
            )
            next_message_ids[item.key] = int(message.id)
            await self._pace_message_refresh()
        for key, message_id in current_message_ids.items():
            if key not in next_message_ids:
                await self._delete_message_id(channel, message_id)
        self.state.message_ids = next_message_ids
        self._save_state()

    async def channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not hasattr(channel, "send"):
            raise RuntimeError("service_status_channel_not_messageable")
        return channel

    async def handle_service_press(self, interaction: discord.Interaction, item: ServiceStatusItem) -> None:
        result = self.last_results.get(item.key) or await self.check_service(item)
        if result.healthy:
            await interaction.response.send_message(
                f"{item.label} is healthy. {result.detail}".strip(),
                ephemeral=True,
                delete_after=5,
                allowed_mentions=NO_MENTIONS,
            )
            return
        if result.state == "unknown":
            await interaction.response.send_message(
                f"{item.label} health is unknown. Configure a health probe first.",
                ephemeral=True,
                delete_after=5,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await self.request_restart(item.key)
        await interaction.response.send_message(
            f"Restart requested for {item.label}.",
            ephemeral=True,
            delete_after=5,
            allowed_mentions=NO_MENTIONS,
        )

    async def request_restart(self, key: str) -> None:
        requests = dict(self.state.restart_requests or {})
        requests[key] = int(requests.get(key, 0)) + 1
        self.state.restart_requests = requests
        self._save_state()

    def status(self) -> dict[str, object]:
        message_ids = dict(self.state.message_ids or {})
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "messageCount": len(message_ids),
            "messageIds": {key: str(value) for key, value in message_ids.items()},
            "serviceCount": len(SERVICES),
            "dummyHealth": False,
            "checks": {key: result.__dict__ for key, result in self.last_results.items()},
            "restartRequests": dict(self.state.restart_requests or {}),
        }

    async def check_services(self) -> dict[str, ServiceProbeResult]:
        pairs = await asyncio.gather(*(self.check_service(item) for item in SERVICES))
        results = {result.key: result for result in pairs}
        self.last_results = results
        return results

    async def check_service(self, item: ServiceStatusItem) -> ServiceProbeResult:
        return await asyncio.to_thread(check_service, item, self.environment, self.timeout_seconds)

    async def _upsert_service_message(
        self,
        channel: discord.abc.Messageable,
        item: ServiceStatusItem,
        *,
        result: ServiceProbeResult,
        message_id: int,
    ) -> discord.Message:
        content = render_service_message(item, result)
        embed = render_service_embed(item, result)
        view = ServiceStatusView(self, item, result) if result.state == "down" else None
        if message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(message_id)
                if _message_matches(message, content=content, embed=embed, view=view):
                    return message
                return await message.edit(content=content, embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("Service status message %s for %s missing; recreating", message_id, item.key)
        return await channel.send(content=content, embed=embed, view=view, allowed_mentions=NO_MENTIONS)

    async def _pace_message_refresh(self) -> None:
        if self.message_refresh_delay_seconds > 0:
            await asyncio.sleep(self.message_refresh_delay_seconds)

    async def _delete_message_id(self, channel: discord.abc.Messageable, message_id: int) -> None:
        if not message_id or not hasattr(channel, "fetch_message"):
            return
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except (discord.NotFound, discord.HTTPException):
            LOGGER.info("Could not delete stale service status message %s", message_id)

    def _load_state(self) -> DiscordServiceStatusState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DiscordServiceStatusState()
        try:
            return DiscordServiceStatusState(
                message_ids={
                    str(key): int(value)
                    for key, value in dict(raw.get("messageIds") or {}).items()
                    if str(key) and int(value)
                },
                legacy_message_id=int(raw.get("messageId") or 0),
                restart_requests={
                    str(key): int(value)
                    for key, value in dict(raw.get("restartRequests") or {}).items()
                    if str(key)
                },
            )
        except (TypeError, ValueError):
            return DiscordServiceStatusState()

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "messageIds": dict(self.state.message_ids or {}),
            "restartRequests": dict(self.state.restart_requests or {}),
        }
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o660)
        temporary.replace(self.state_path)


class ServiceStatusView(discord.ui.View):
    def __init__(
        self,
        surface: DiscordServiceStatusSurface,
        item: ServiceStatusItem,
        result: ServiceProbeResult,
    ) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        button = discord.ui.Button(
            label="Restart",
            style=discord.ButtonStyle.danger,
            custom_id=f"system-status:{item.key}",
        )
        button.callback = self._callback(item)
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.surface.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def _callback(self, item: ServiceStatusItem):
        async def callback(interaction: discord.Interaction) -> None:
            await self.surface.handle_service_press(interaction, item)

        return callback


def render_service_message(item: ServiceStatusItem, result: ServiceProbeResult | None = None) -> str:
    return ""


def render_service_embed(item: ServiceStatusItem, result: ServiceProbeResult | None = None) -> discord.Embed:
    result = result or ServiceProbeResult(item.key, "unknown", "", "No health probe configured.")
    status = status_label(result)
    checked = f" · {result.checked_at}" if result.checked_at else ""
    detail = f"\n{result.detail}" if result.detail else ""
    embed = discord.Embed(
        title=item.label,
        description=f"{item.description}\n\n**{status}**{checked}{detail}",
        color=service_embed_color(result),
    )
    return embed


def service_embed_color(result: ServiceProbeResult) -> int:
    if result.state == "healthy":
        return EMBED_COLOR_HEALTHY
    if result.state == "down":
        return EMBED_COLOR_DOWN
    return EMBED_COLOR_UNKNOWN


def status_label(result: ServiceProbeResult) -> str:
    if result.state == "healthy":
        return "Healthy"
    if result.state == "down":
        return "Down"
    return "Unknown"


def check_service(
    item: ServiceStatusItem,
    env: Mapping[str, str],
    timeout_seconds: float,
) -> ServiceProbeResult:
    checked_at = time.strftime("%H:%M:%S", time.localtime())
    url = probe_value(env, item.key, "URL")
    if not url and default_probes_enabled(env):
        url = default_http_probe(env, item.key)
    tcp = probe_value(env, item.key, "TCP")
    if url:
        state, detail = check_http(url, timeout_seconds)
        return ServiceProbeResult(item.key, state, checked_at, detail)
    if tcp:
        state, detail = check_tcp(tcp, timeout_seconds)
        return ServiceProbeResult(item.key, state, checked_at, detail)
    return ServiceProbeResult(item.key, "unknown", checked_at, "No health probe configured.")


def check_http(url: str, timeout_seconds: float) -> tuple[str, str]:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "KaosGovernor/service-status"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "down", stable_error(exc)
    if 200 <= status < 400 or status in OK_HTTP_STATUSES:
        return "healthy", f"HTTP {status}"
    return "down", f"HTTP {status}"


def check_tcp(target: str, timeout_seconds: float) -> tuple[str, str]:
    host, separator, port_text = target.rpartition(":")
    if not separator or not host:
        return "unknown", "Invalid TCP probe."
    try:
        port = int(port_text)
    except ValueError:
        return "unknown", "Invalid TCP probe."
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return "healthy", f"TCP {host}:{port}"
    except OSError as exc:
        return "down", stable_error(exc)


def probe_value(env: Mapping[str, str], key: str, suffix: str) -> str:
    return env.get(f"SERVICE_STATUS_{key.upper()}_{suffix}", "").strip()


def default_http_probe(env: Mapping[str, str], key: str) -> str:
    if key == "paperless":
        return env.get("PAPERLESS_BASE_URL", "").strip() or env.get("PAPERLESS_INTERNAL_URL", "").strip()
    if key == "kaosgovernor":
        port = env.get("HEALTH_PORT", "8097").strip() or "8097"
        return f"http://127.0.0.1:{port}/health"
    return DEFAULT_HTTP_PROBES.get(key, "")


def service_status_timeout_seconds(env: Mapping[str, str]) -> float:
    raw = env.get("SERVICE_STATUS_TIMEOUT_SECONDS", "3").strip()
    try:
        value = float(raw)
    except ValueError:
        return 3.0
    return min(max(value, 0.5), 30.0)


def service_status_refresh_seconds(env: Mapping[str, str]) -> int:
    raw = env.get("SERVICE_STATUS_REFRESH_SECONDS", "300").strip()
    try:
        value = int(raw)
    except ValueError:
        return 300
    return min(max(value, 30), 3600)


def default_probes_enabled(env: Mapping[str, str]) -> bool:
    return env.get("SERVICE_STATUS_DEFAULT_PROBES_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def stable_error(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if reason:
        return str(reason)[:120]
    return exc.__class__.__name__


def _message_matches(
    message: discord.Message,
    *,
    content: str,
    embed: discord.Embed | None,
    view: discord.ui.View | None,
) -> bool:
    current_embed = getattr(message, "embeds", [])[:1]
    return (
        str(getattr(message, "content", "") or "") == content
        and _embed_signature(current_embed[0] if current_embed else None) == _embed_signature(embed)
        and _message_view_signature(message) == _view_signature(view)
    )


def _embed_signature(embed: discord.Embed | None) -> dict[str, object]:
    return embed.to_dict() if embed is not None else {}


def _message_view_signature(message: discord.Message) -> tuple[tuple[str, str], ...]:
    view = getattr(message, "view", None)
    if view is not None:
        return _view_signature(view)
    signature: list[tuple[str, str]] = []
    for row in getattr(message, "components", []) or []:
        for item in getattr(row, "children", []) or []:
            signature.append((str(getattr(item, "custom_id", "") or ""), str(getattr(item, "label", "") or "")))
    return tuple(signature)


def _view_signature(view: discord.ui.View | None) -> tuple[tuple[str, str], ...]:
    if view is None:
        return ()
    return tuple(
        (
            str(getattr(item, "custom_id", "") or ""),
            str(getattr(item, "label", "") or ""),
        )
        for item in getattr(view, "children", [])
    )
