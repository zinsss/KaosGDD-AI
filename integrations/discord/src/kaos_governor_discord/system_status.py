from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path

import discord

from .access import AccessPolicy
from .markdown import NO_MENTIONS


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceStatusItem:
    key: str
    label: str
    description: str
    healthy: bool = True


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


class DiscordServiceStatusSurface:
    def __init__(
        self,
        bot: discord.Client,
        policy: AccessPolicy,
        *,
        channel_id: int,
        state_path: Path,
    ) -> None:
        self.bot = bot
        self.policy = policy
        self.channel_id = channel_id
        self.state_path = state_path
        self.state = self._load_state()

    async def ensure_message(self) -> None:
        channel = await self.channel()
        if self.state.legacy_message_id:
            await self._delete_message_id(channel, self.state.legacy_message_id)
            self.state.legacy_message_id = 0
        next_message_ids: dict[str, int] = {}
        current_message_ids = dict(self.state.message_ids or {})
        for item in SERVICES:
            message = await self._upsert_service_message(
                channel,
                item,
                message_id=current_message_ids.get(item.key, 0),
            )
            next_message_ids[item.key] = int(message.id)
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
        if item.healthy:
            await interaction.response.send_message(
                f"{item.label} is healthy.",
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
            "dummyHealth": True,
            "restartRequests": dict(self.state.restart_requests or {}),
        }

    async def _upsert_service_message(
        self,
        channel: discord.abc.Messageable,
        item: ServiceStatusItem,
        *,
        message_id: int,
    ) -> discord.Message:
        content = render_service_message(item)
        view = ServiceStatusView(self, item)
        if message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(message_id)
                return await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("Service status message %s for %s missing; recreating", message_id, item.key)
        return await channel.send(content=content, view=view, allowed_mentions=NO_MENTIONS)

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
    def __init__(self, surface: DiscordServiceStatusSurface, item: ServiceStatusItem) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        button = discord.ui.Button(
            label="Healthy" if item.healthy else "Restart",
            style=discord.ButtonStyle.success if item.healthy else discord.ButtonStyle.danger,
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


def render_service_message(item: ServiceStatusItem) -> str:
    return "\n".join(
        (
            f"# {item.label}",
            item.description,
        )
    )
