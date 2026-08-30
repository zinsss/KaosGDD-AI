from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time
from typing import Mapping
import urllib.error
import urllib.request

import discord
from kaos_governor.notifications import TextNotification, TextNotificationService

from .access import AccessPolicy
from .markdown import NO_MENTIONS


LOGGER = logging.getLogger(__name__)


EMBED_COLOR_HEALTHY = 0xA3BE8C
EMBED_COLOR_DOWN = 0xBF616A
EMBED_COLOR_UNKNOWN = 0x4C566A
MESSAGE_REFRESH_DELAY_SECONDS = 1.25
HEALTHY_SUMMARY_KEY = "summary:healthy"
PLANNED_SUMMARY_KEY = "summary:planned"


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


@dataclass(frozen=True)
class RestartResult:
    key: str
    state: str
    detail: str = ""

    def user_message(self, label: str) -> str:
        if self.state == "dry_run":
            return f"Restart dry-run for {label}: {self.detail}".strip()
        if self.state == "executed":
            return f"Restart executed for {label}."
        if self.state == "not_allowed":
            return f"Restart recorded for {label}. Execution is not allowed."
        if self.state == "not_configured":
            return f"Restart recorded for {label}. No restart command is configured."
        return f"Restart failed for {label}. {self.detail}".strip()


@dataclass
class DiscordServiceStatusState:
    message_ids: dict[str, int] | None = None
    legacy_message_id: int = 0
    restart_requests: dict[str, int] | None = None
    restart_results: dict[str, str] | None = None
    restart_audit: list[dict[str, object]] | None = None
    service_states: dict[str, str] | None = None
    service_incidents: dict[str, int] | None = None


SERVICES: tuple[ServiceStatusItem, ...] = (
    ServiceStatusItem("kaosbrain", "KaosBrain", "Brain of KaosGDD on Odroid H4 Ultra"),
    ServiceStatusItem("kaosai-second-look", "KaosAI Second-Look", "Temporary AIO image second-look provider path"),
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

PLANNED_SERVICE_DETAILS = {
    "kaosinj": "Planned. No service is deployed yet.",
}

OK_HTTP_STATUSES = {200, 204, 301, 302, 307, 308, 401, 403}
RESTART_TIMEOUT_SECONDS = 30.0


class DiscordServiceStatusSurface:
    def __init__(
        self,
        bot: discord.Client,
        policy: AccessPolicy,
        *,
        channel_id: int,
        state_path: Path,
        environment: Mapping[str, str] | None = None,
        text_notifications: TextNotificationService | None = None,
    ) -> None:
        self.bot = bot
        self.policy = policy
        self.channel_id = channel_id
        self.state_path = state_path
        self.state = self._load_state()
        self.environment = os.environ if environment is None else environment
        self.text_notifications = text_notifications
        self.timeout_seconds = service_status_timeout_seconds(self.environment)
        self.refresh_seconds = service_status_refresh_seconds(self.environment)
        self.message_refresh_delay_seconds = MESSAGE_REFRESH_DELAY_SECONDS
        self.last_results: dict[str, ServiceProbeResult] = {}

    async def ensure_message(self) -> None:
        channel = await self.channel()
        results = await self.check_services()
        await self._notify_service_state_changes(results)
        if self.state.legacy_message_id:
            await self._delete_message_id(channel, self.state.legacy_message_id)
            self.state.legacy_message_id = 0
        next_message_ids: dict[str, int] = {}
        current_message_ids = dict(self.state.message_ids or {})
        healthy_items = [item for item in SERVICES if results[item.key].state == "healthy"]
        planned_items = [item for item in SERVICES if results[item.key].state == "planned"]
        if healthy_items:
            message = await self._upsert_embed_message(
                channel,
                key=HEALTHY_SUMMARY_KEY,
                embed=render_summary_embed(
                    "Healthy",
                    healthy_items,
                    EMBED_COLOR_HEALTHY,
                    updated_at=summary_updated_at(healthy_items, results),
                ),
                message_id=current_message_ids.get(HEALTHY_SUMMARY_KEY, 0),
            )
            next_message_ids[HEALTHY_SUMMARY_KEY] = int(message.id)
            await self._pace_message_refresh()
        for item in SERVICES:
            if results[item.key].state in {"healthy", "planned"}:
                continue
            message_key = service_issue_key(item.key)
            message = await self._upsert_service_message(
                channel,
                item,
                result=results[item.key],
                message_id=current_message_ids.get(message_key, 0) or current_message_ids.get(item.key, 0),
            )
            next_message_ids[message_key] = int(message.id)
            await self._pace_message_refresh()
        if planned_items:
            message = await self._upsert_embed_message(
                channel,
                key=PLANNED_SUMMARY_KEY,
                embed=render_summary_embed(
                    "Planned",
                    planned_items,
                    EMBED_COLOR_UNKNOWN,
                    updated_at=summary_updated_at(planned_items, results),
                ),
                message_id=current_message_ids.get(PLANNED_SUMMARY_KEY, 0),
            )
            next_message_ids[PLANNED_SUMMARY_KEY] = int(message.id)
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
        await interaction.response.send_message(
            f"Restart {item.label}?",
            ephemeral=True,
            view=ServiceRestartConfirmView(self, item, int(interaction.user.id)),
            allowed_mentions=NO_MENTIONS,
        )

    async def request_restart(self, key: str, *, actor_id: int | None = None) -> "RestartResult":
        requests = dict(self.state.restart_requests or {})
        requests[key] = int(requests.get(key, 0)) + 1
        self.state.restart_requests = requests
        result = await restart_service(key, self.environment)
        results = dict(self.state.restart_results or {})
        results[key] = result.state
        self.state.restart_results = results
        audit = list(self.state.restart_audit or [])
        audit.append(
            {
                "key": result.key,
                "state": result.state,
                "actorId": str(actor_id or ""),
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            }
        )
        self.state.restart_audit = audit[-50:]
        self._save_state()
        return result

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
            "restartResults": dict(self.state.restart_results or {}),
            "restartAudit": list(self.state.restart_audit or []),
        }

    async def check_services(self) -> dict[str, ServiceProbeResult]:
        pairs = await asyncio.gather(*(self.check_service(item) for item in SERVICES))
        results = {result.key: result for result in pairs}
        self.last_results = results
        return results

    async def check_service(self, item: ServiceStatusItem) -> ServiceProbeResult:
        return await asyncio.to_thread(check_service, item, self.environment, self.timeout_seconds)

    async def _notify_service_state_changes(
        self,
        results: Mapping[str, ServiceProbeResult],
    ) -> None:
        previous = dict(self.state.service_states or {})
        incidents = dict(self.state.service_incidents or {})
        labels = {item.key: item.label for item in SERVICES}
        for key, result in results.items():
            old_state = previous.get(key, "")
            if result.state == "down" and old_state != "down":
                incident = int(incidents.get(key, 0)) + 1
                incidents[key] = incident
                await self._send_text_notification(
                    TextNotification(
                        key=f"system:service:{key}:down:{incident}",
                        category="system",
                        title="",
                        message=f"{labels.get(key, key)} is down.",
                    )
                )
            elif old_state == "down" and result.state == "healthy":
                incident = max(1, int(incidents.get(key, 0)))
                await self._send_text_notification(
                    TextNotification(
                        key=f"system:service:{key}:back:{incident}",
                        category="system",
                        title="",
                        message=f"{labels.get(key, key)} is back.",
                    )
                )
        self.state.service_states = {key: result.state for key, result in results.items()}
        self.state.service_incidents = incidents

    async def _send_text_notification(self, notification: TextNotification) -> None:
        if self.text_notifications is None:
            return
        try:
            await asyncio.to_thread(self.text_notifications.notify, notification)
        except Exception:
            LOGGER.exception("Failed to queue service status text alert: %s", notification.key)

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
                    self._register_view(view, int(message.id))
                    return message
                return await message.edit(content=content, embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("Service status message %s for %s missing; recreating", message_id, item.key)
        return await channel.send(content=content, embed=embed, view=view, allowed_mentions=NO_MENTIONS)

    async def _upsert_embed_message(
        self,
        channel: discord.abc.Messageable,
        *,
        key: str,
        embed: discord.Embed,
        message_id: int,
    ) -> discord.Message:
        content = ""
        if message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(message_id)
                if _message_matches(message, content=content, embed=embed, view=None):
                    return message
                return await message.edit(content=content, embed=embed, view=None, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("Service status summary message %s for %s missing; recreating", message_id, key)
        return await channel.send(content=content, embed=embed, view=None, allowed_mentions=NO_MENTIONS)

    def _register_view(self, view: discord.ui.View | None, message_id: int) -> None:
        if view is None or not hasattr(self.bot, "add_view"):
            return
        try:
            self.bot.add_view(view, message_id=message_id)
        except ValueError:
            LOGGER.info("Could not register persistent service status view for message %s", message_id)

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
                restart_results={
                    str(key): str(value)
                    for key, value in dict(raw.get("restartResults") or {}).items()
                    if str(key)
                },
                restart_audit=[
                    dict(item)
                    for item in list(raw.get("restartAudit") or [])
                    if isinstance(item, dict)
                ][-50:],
                service_states={
                    str(key): str(value)
                    for key, value in dict(raw.get("serviceStates") or {}).items()
                    if str(key)
                },
                service_incidents={
                    str(key): int(value)
                    for key, value in dict(raw.get("serviceIncidents") or {}).items()
                    if str(key) and int(value) > 0
                },
            )
        except (TypeError, ValueError):
            return DiscordServiceStatusState()

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "messageIds": dict(self.state.message_ids or {}),
            "restartRequests": dict(self.state.restart_requests or {}),
            "restartResults": dict(self.state.restart_results or {}),
            "restartAudit": list(self.state.restart_audit or []),
            "serviceStates": dict(self.state.service_states or {}),
            "serviceIncidents": dict(self.state.service_incidents or {}),
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


class ServiceRestartConfirmView(discord.ui.View):
    def __init__(self, surface: DiscordServiceStatusSurface, item: ServiceStatusItem, owner_id: int) -> None:
        super().__init__(timeout=60)
        self.surface = surface
        self.item = item
        self.owner_id = owner_id
        confirm = discord.ui.Button(
            label="Confirm Restart",
            style=discord.ButtonStyle.danger,
            custom_id=f"system-status:restart-confirm:{item.key}",
        )
        cancel = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id=f"system-status:restart-cancel:{item.key}",
        )
        confirm.callback = self._confirm
        cancel.callback = self._cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id and self.surface.policy.allows(
            interaction.guild_id,
            interaction.channel_id,
            interaction.user.id,
        ):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _confirm(self, interaction: discord.Interaction) -> None:
        result = await self.surface.request_restart(self.item.key, actor_id=int(interaction.user.id))
        await interaction.response.edit_message(
            content=result.user_message(self.item.label),
            view=None,
            allowed_mentions=NO_MENTIONS,
        )

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content=f"Restart canceled for {self.item.label}.",
            view=None,
            allowed_mentions=NO_MENTIONS,
        )


def render_service_message(item: ServiceStatusItem, result: ServiceProbeResult | None = None) -> str:
    return ""


def render_service_embed(item: ServiceStatusItem, result: ServiceProbeResult | None = None) -> discord.Embed:
    result = result or ServiceProbeResult(item.key, "unknown", "", "No health probe configured.")
    status = status_label(result)
    detail = f"\n{result.detail}" if result.detail else ""
    embed = discord.Embed(
        title=item.label,
        description=f"{item.description}\n\n**{status}**{detail}",
        color=service_embed_color(result),
    )
    if result.checked_at:
        embed.set_footer(text=f"Updated at {result.checked_at}")
    return embed


def render_summary_embed(
    title: str,
    items: list[ServiceStatusItem],
    color: int,
    *,
    updated_at: str = "",
) -> discord.Embed:
    description = "\n".join(f"**{item.label}**\n{item.description}" for item in items) or "None"
    embed = discord.Embed(title=title, description=description, color=color)
    if updated_at:
        embed.set_footer(text=f"Updated at {updated_at}")
    return embed


def service_issue_key(key: str) -> str:
    return f"issue:{key}"


def summary_updated_at(
    items: list[ServiceStatusItem],
    results: Mapping[str, ServiceProbeResult],
) -> str:
    for item in items:
        value = results[item.key].checked_at
        if value:
            return value
    return ""


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
    if result.state == "planned":
        return "Planned"
    return "Unknown"


def check_service(
    item: ServiceStatusItem,
    env: Mapping[str, str],
    timeout_seconds: float,
) -> ServiceProbeResult:
    checked_at = checked_at_text()
    if item.key == "kaosai-second-look":
        state, detail = check_second_look_status(env, timeout_seconds)
        return ServiceProbeResult(item.key, state, checked_at, detail)
    url = probe_value(env, item.key, "URL")
    if not url and default_probes_enabled(env):
        url = default_http_probe(env, item.key)
    tcp = probe_value(env, item.key, "TCP")
    if url:
        if item.key == "kaosbrain":
            state, detail = check_brain_http(url, timeout_seconds)
        else:
            state, detail = check_http(url, timeout_seconds)
        return ServiceProbeResult(item.key, state, checked_at, detail)
    if tcp:
        state, detail = check_tcp(tcp, timeout_seconds)
        return ServiceProbeResult(item.key, state, checked_at, detail)
    if item.key in PLANNED_SERVICE_DETAILS:
        return ServiceProbeResult(item.key, "planned", checked_at, PLANNED_SERVICE_DETAILS[item.key])
    return ServiceProbeResult(item.key, "unknown", checked_at, "No health probe configured.")


def checked_at_text() -> str:
    kst = timezone(timedelta(hours=9), "KST")
    return datetime.now(kst).strftime("%H:%M:%S KST")


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


def check_brain_http(url: str, timeout_seconds: float) -> tuple[str, str]:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "KaosGovernor/service-status"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            body = response.read(8192)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(8192)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "down", stable_error(exc)
    if 200 <= status < 400 or status in OK_HTTP_STATUSES:
        return "healthy", brain_health_detail(status, body)
    return "down", f"HTTP {status}"


def brain_health_detail(status: int, body: bytes) -> str:
    detail = f"HTTP {status}"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return detail
    if not isinstance(payload, dict):
        return detail
    parts = [detail]
    if "discordReady" in payload:
        parts.append(f"ready={bool(payload.get('discordReady'))}")
    kaosai = payload.get("kaosAI")
    if isinstance(kaosai, dict):
        mode = str(kaosai.get("mode") or "").strip()
        if mode:
            parts.append(f"KaosAI {mode}")
    chat_model = str(payload.get("chatModel") or "").strip()
    deep_model = str(payload.get("deepModel") or "").strip()
    if chat_model or deep_model:
        parts.append(f"models {chat_model or '?'} / {deep_model or '?'}")
    return "; ".join(parts)


def check_second_look_status(env: Mapping[str, str], timeout_seconds: float) -> tuple[str, str]:
    governor_url = env.get("IMAGING_SECOND_LOOK_URL", "").strip()
    provider_url = env.get("SERVICE_STATUS_KAOSAI_SECOND_LOOK_URL", "").strip()
    if not provider_url:
        provider_url = second_look_health_url(governor_url)
    if not provider_url:
        return "unknown", "IMAGING_SECOND_LOOK_URL is not configured."
    state, detail = check_second_look_provider_http(provider_url, timeout_seconds)
    if state != "healthy":
        return state, detail
    status_detail = check_second_look_governor_status(env, timeout_seconds)
    if status_detail:
        detail = f"{detail}; {status_detail}"
    if governor_url:
        return state, f"{detail}; Governor route configured"
    return state, detail


def check_second_look_governor_status(env: Mapping[str, str], timeout_seconds: float) -> str:
    url = env.get("SERVICE_STATUS_KAOSAI_SECOND_LOOK_STATUS_URL", "").strip()
    if not url:
        port = env.get("GOVERNOR_BRAIN_TOOLS_PORT", "8098").strip() or "8098"
        url = f"http://127.0.0.1:{port}/tools/imaging/second-look/status"
    token = service_status_secret(env, "SERVICE_STATUS_KAOSAI_SECOND_LOOK_STATUS_TOKEN") or service_status_secret(
        env,
        "GOVERNOR_API_TOKEN",
    )
    if not token:
        return "last unavailable: missing status token"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "KaosGovernor/service-status",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            body = response.read(8192)
    except urllib.error.HTTPError as exc:
        return f"last unavailable: HTTP {int(exc.code)}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"last unavailable: {stable_error(exc)}"
    if not 200 <= status < 400:
        return f"last unavailable: HTTP {status}"
    return second_look_status_detail(body)


def service_status_secret(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if value:
        return value
    path = env.get(f"{name}_FILE", "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def check_second_look_provider_http(url: str, timeout_seconds: float) -> tuple[str, str]:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "KaosGovernor/service-status"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            body = response.read(8192)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(8192)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "down", stable_error(exc)
    if status == 401:
        return "healthy", "Provider reachable; auth required"
    if 200 <= status < 400:
        return "healthy", second_look_health_detail(status, body)
    return "down", f"HTTP {status}"


def second_look_health_url(url: str) -> str:
    normalized = url.strip()
    if normalized.endswith("/imaging/second-look"):
        return normalized[: -len("/imaging/second-look")] + "/health"
    if normalized.endswith("/tools/imaging/second-look"):
        return normalized[: -len("/tools/imaging/second-look")] + "/health"
    return normalized


def second_look_health_detail(status: int, body: bytes) -> str:
    detail = f"HTTP {status}"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return detail
    if not isinstance(payload, dict):
        return detail
    parts = [detail]
    imaging_provider = str(payload.get("imagingProvider") or "").strip()
    imaging_model = str(payload.get("imagingModel") or "").strip()
    if imaging_provider:
        parts.append(f"provider={imaging_provider}")
    if imaging_model:
        parts.append(f"model={imaging_model}")
    return "; ".join(parts)


def second_look_status_detail(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "last unavailable: invalid status"
    if not isinstance(payload, dict):
        return "last unavailable: invalid status"
    status = payload.get("secondLook")
    if not isinstance(status, dict):
        return "last unavailable: missing status"
    request_count = second_look_status_count(status, "requestCount")
    completed_count = second_look_status_count(status, "completedCount")
    failed_count = second_look_status_count(status, "failedCount")
    rate_limited_count = second_look_status_count(status, "rateLimitedCount")
    if request_count == 0:
        return "no second-look requests yet"
    last_status = str(status.get("lastStatus") or "unknown").strip() or "unknown"
    last_model = str(status.get("lastModel") or "").strip()
    last_completed = str(status.get("lastCompletedAt") or "").strip()
    last_failed = str(status.get("lastFailedAt") or "").strip()
    last_error = str(status.get("lastError") or "").strip()
    if last_status == "completed":
        detail = f"last completed {last_completed or 'unknown'}"
        if last_model:
            detail = f"{detail}, model {last_model}"
    elif last_error:
        detail = f"last failed {last_failed or 'unknown'}: {last_error}"
    else:
        detail = f"last {last_status}"
    detail = f"{detail}; requests {request_count}, completed {completed_count}, failed {failed_count}"
    if rate_limited_count:
        detail = f"{detail}, rate-limited {rate_limited_count}"
    return detail


def second_look_status_count(status: Mapping[str, object], key: str) -> int:
    try:
        return int(status.get(key) or 0)
    except (TypeError, ValueError):
        return 0


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


async def restart_service(key: str, env: Mapping[str, str]) -> RestartResult:
    return await asyncio.to_thread(restart_service_sync, key, env)


def restart_service_sync(key: str, env: Mapping[str, str]) -> RestartResult:
    normalized = key.strip().lower()
    allowed = restart_allowed_keys(env)
    if normalized not in allowed:
        return RestartResult(normalized, "not_allowed")
    command = restart_command(env, normalized)
    if not command:
        return RestartResult(normalized, "not_configured")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return RestartResult(normalized, "failed", f"Invalid command: {stable_error(exc)}")
    if not argv:
        return RestartResult(normalized, "not_configured")
    mode = restart_mode(env)
    if mode == "dry_run":
        return RestartResult(normalized, "dry_run", shlex.join(argv))
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=restart_timeout_seconds(env),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RestartResult(normalized, "failed", stable_error(exc))
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        return RestartResult(normalized, "failed", detail[:160])
    return RestartResult(normalized, "executed", (completed.stdout or "").strip()[:160])


def restart_allowed_keys(env: Mapping[str, str]) -> frozenset[str]:
    raw = env.get("SERVICE_STATUS_RESTART_ALLOWED_KEYS", "").strip()
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def restart_command(env: Mapping[str, str], key: str) -> str:
    return env.get(f"SERVICE_STATUS_{key.upper()}_RESTART_COMMAND", "").strip()


def restart_timeout_seconds(env: Mapping[str, str]) -> float:
    raw = env.get("SERVICE_STATUS_RESTART_TIMEOUT_SECONDS", str(RESTART_TIMEOUT_SECONDS)).strip()
    try:
        value = float(raw)
    except ValueError:
        return RESTART_TIMEOUT_SECONDS
    return min(max(value, 1.0), 120.0)


def restart_mode(env: Mapping[str, str]) -> str:
    raw = env.get("SERVICE_STATUS_RESTART_MODE", "dry_run").strip().lower().replace("-", "_")
    if raw in {"execute", "enabled", "real"}:
        return "execute"
    return "dry_run"


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
