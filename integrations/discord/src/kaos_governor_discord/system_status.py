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
    healthy: bool = True


@dataclass
class DiscordServiceStatusState:
    message_id: int = 0
    restart_requests: dict[str, int] | None = None


SERVICE_ROWS: tuple[tuple[ServiceStatusItem, ...], ...] = (
    (
        ServiceStatusItem("kaosbrain", "KaosBrain"),
        ServiceStatusItem("kaosgovernor", "KaosGovernor"),
    ),
    (
        ServiceStatusItem("kaospacs", "KaosPACS"),
        ServiceStatusItem("kaosinj", "KaosInj"),
    ),
    (
        ServiceStatusItem("radicale", "Radicale"),
        ServiceStatusItem("memos", "Memos"),
    ),
    (
        ServiceStatusItem("paperless", "Paperless"),
        ServiceStatusItem("stirlingpdf", "SterlingPDF"),
    ),
    (
        ServiceStatusItem("vaultwarden", "Vaultwarden"),
        ServiceStatusItem("rustdesk", "Rustdesk"),
    ),
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
        content = render_status_message()
        view = ServiceStatusView(self)
        if self.state.message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(self.state.message_id)
                await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
                return
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("Service status message %s missing; recreating", self.state.message_id)
        message = await channel.send(content=content, view=view, allowed_mentions=NO_MENTIONS)
        self.state.message_id = int(message.id)
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
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "messageId": str(self.state.message_id) if self.state.message_id else "",
            "serviceCount": sum(len(row) for row in SERVICE_ROWS),
            "dummyHealth": True,
            "restartRequests": dict(self.state.restart_requests or {}),
        }

    def _load_state(self) -> DiscordServiceStatusState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DiscordServiceStatusState()
        try:
            return DiscordServiceStatusState(
                message_id=int(raw.get("messageId") or 0),
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
            "messageId": self.state.message_id,
            "restartRequests": dict(self.state.restart_requests or {}),
        }
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o660)
        temporary.replace(self.state_path)


class ServiceStatusView(discord.ui.View):
    def __init__(self, surface: DiscordServiceStatusSurface) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        for row_index, row in enumerate(SERVICE_ROWS):
            for item in row:
                button = discord.ui.Button(
                    label=item.label,
                    style=discord.ButtonStyle.success if item.healthy else discord.ButtonStyle.danger,
                    custom_id=f"system-status:{item.key}",
                    row=row_index,
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


def render_status_message() -> str:
    return "\n".join(
        (
            "## System",
            "",
            "Service health board",
        )
    )
