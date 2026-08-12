from __future__ import annotations

import logging
import time

import discord
from discord import app_commands

from . import __version__
from .access import AccessPolicy
from .config import Settings
from .health import HealthServer

LOGGER = logging.getLogger(__name__)


async def _deny(interaction: discord.Interaction) -> None:
    message = "KaosGovernor is restricted to its configured server, channels, and users."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class GovernorCommandTree(app_commands.CommandTree):
    def __init__(self, client: discord.Client, policy: AccessPolicy) -> None:
        super().__init__(client)
        self._policy = policy

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        LOGGER.warning("Rejected interaction guild=%s channel=%s user=%s", interaction.guild_id, interaction.channel_id, interaction.user.id)
        await _deny(interaction)
        return False


class ConfirmationTestView(discord.ui.View):
    def __init__(self, owner_id: int, policy: AccessPolicy) -> None:
        super().__init__(timeout=60)
        self._owner_id = owner_id
        self._policy = policy
        self.message: discord.InteractionMessage | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._owner_id or not self._policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            await _deny(interaction)
            return False
        return True

    async def _finish(self, interaction: discord.Interaction, result: str) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=result, view=self)
        self.stop()

    @discord.ui.button(label="Confirm test", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(interaction, "Confirmation transport verified. No action was performed.")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(interaction, "Confirmation test cancelled.")

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="Confirmation test expired.", view=self)
            except discord.HTTPException:
                LOGGER.info("Could not update expired ephemeral confirmation test")


class GovernorBot(discord.Client):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)
        self.settings = settings
        self.policy = AccessPolicy(settings.guild_id, settings.allowed_user_ids, settings.allowed_channel_ids)
        self.tree = GovernorCommandTree(self, self.policy)
        self._started_at = time.monotonic()
        self._startup_announced = False
        self._health = HealthServer(settings.health_host, settings.health_port, self._health_status)
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="status", description="Show KaosGovernor bot transport status")
        async def status(interaction: discord.Interaction) -> None:
            uptime = int(time.monotonic() - self._started_at)
            await interaction.response.send_message(
                f"**KaosGovernor transport**\nVersion: `{__version__}`\nUptime: `{uptime}s`\nDiscord: `connected`\nGovernor API: `not connected (preparation mode)`",
                ephemeral=True,
            )

        @self.tree.command(name="confirmation-test", description="Test an expiring confirmation without performing an action")
        async def confirmation_test(interaction: discord.Interaction) -> None:
            view = ConfirmationTestView(interaction.user.id, self.policy)
            await interaction.response.send_message("This test expires in 60 seconds and performs no Governor operation.", view=view, ephemeral=True)
            view.message = await interaction.original_response()

    async def setup_hook(self) -> None:
        await self._health.start()
        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        LOGGER.info("Synced %d commands to guild %s", len(synced), self.settings.guild_id)

    async def on_ready(self) -> None:
        LOGGER.info("Discord ready as %s (%s)", self.user, self.user.id if self.user else None)
        if self.settings.startup_notification and not self._startup_announced and self.settings.system_channel_id:
            self._startup_announced = True
            try:
                channel = self.get_channel(self.settings.system_channel_id) or await self.fetch_channel(self.settings.system_channel_id)
                if not isinstance(channel, discord.abc.Messageable):
                    raise TypeError("configured system channel is not messageable")
                await channel.send(f"KaosGovernor Discord transport `{__version__}` is online.")
            except (discord.HTTPException, TypeError):
                LOGGER.exception("Failed to send startup notification")

    async def close(self) -> None:
        await self._health.stop()
        await super().close()

    def _health_status(self) -> dict[str, object]:
        return {"discordReady": self.is_ready(), "guildId": str(self.settings.guild_id), "version": __version__}
