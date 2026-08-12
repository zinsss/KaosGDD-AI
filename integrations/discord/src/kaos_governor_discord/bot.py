from __future__ import annotations

import asyncio
from contextlib import suppress
import io
import logging
import time

import discord
from discord import app_commands
from kaos_governor.mail import Attachment, MailMessage, NaverMailConfig, NaverMailPoller

from . import __version__
from .access import AccessPolicy
from .config import Settings
from .health import HealthServer
from .mail import render_mail_summary, safe_attachment_filename
from .markdown import MarkdownField, MarkdownMessage, NO_MENTIONS

LOGGER = logging.getLogger(__name__)


async def _deny(interaction: discord.Interaction) -> None:
    message = MarkdownMessage(
        title="Access denied",
        summary="KaosGovernor is restricted to its configured server, channels, and users.",
    ).render()
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)
    else:
        await interaction.response.send_message(message, ephemeral=True, allowed_mentions=NO_MENTIONS)


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
        await interaction.response.edit_message(content=result, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Confirm test", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(
            interaction,
            MarkdownMessage(
                title="Confirmation verified",
                summary="No Governor operation was performed.",
            ).render(),
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(
            interaction,
            MarkdownMessage(title="Confirmation cancelled").render(),
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=MarkdownMessage(
                        title="Confirmation expired",
                        summary="No Governor operation was performed.",
                    ).render(),
                    view=self,
                    allowed_mentions=NO_MENTIONS,
                )
            except discord.HTTPException:
                LOGGER.info("Could not update expired ephemeral confirmation test")


class GovernorBot(discord.Client):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=NO_MENTIONS)
        self.settings = settings
        self.policy = AccessPolicy(settings.guild_id, settings.allowed_user_ids, settings.allowed_channel_ids)
        self.tree = GovernorCommandTree(self, self.policy)
        self._started_at = time.monotonic()
        self._startup_announced = False
        self._mail_task: asyncio.Task | None = None
        self.mail_poller = NaverMailPoller(NaverMailConfig.from_env())
        self._health = HealthServer(settings.health_host, settings.health_port, self._health_status)
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="status", description="Show KaosGovernor bot transport status")
        async def status(interaction: discord.Interaction) -> None:
            uptime = int(time.monotonic() - self._started_at)
            await interaction.response.send_message(
                MarkdownMessage(
                    title="KaosGovernor",
                    summary="Deterministic Discord transport",
                    fields=(
                        MarkdownField("Version", __version__),
                        MarkdownField("Uptime", f"{uptime}s"),
                    ),
                    bullets=(
                        "Discord: connected",
                        "Governor API: not connected (preparation mode)",
                        f"Naver mail: {'enabled' if self.mail_poller.config.enabled else 'disabled'}",
                    ),
                    footer="Private status visible only to you",
                ).render(),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )

        @self.tree.command(name="confirmation-test", description="Test an expiring confirmation without performing an action")
        async def confirmation_test(interaction: discord.Interaction) -> None:
            view = ConfirmationTestView(interaction.user.id, self.policy)
            await interaction.response.send_message(
                MarkdownMessage(
                    title="Confirmation test",
                    summary="Choose an action below. This performs no Governor operation.",
                    footer="Expires in 60 seconds",
                ).render(),
                view=view,
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            view.message = await interaction.original_response()

    async def setup_hook(self) -> None:
        await self._health.start()
        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        LOGGER.info("Synced %d commands to guild %s", len(synced), self.settings.guild_id)

    async def on_ready(self) -> None:
        LOGGER.info("Discord ready as %s (%s)", self.user, self.user.id if self.user else None)
        if self.mail_poller.config.enabled and self._mail_task is None:
            self._mail_task = asyncio.create_task(self._mail_loop(), name="governor-naver-mail")
        if self.settings.startup_notification and not self._startup_announced and self.settings.system_channel_id:
            self._startup_announced = True
            try:
                channel = self.get_channel(self.settings.system_channel_id) or await self.fetch_channel(self.settings.system_channel_id)
                if not isinstance(channel, discord.abc.Messageable):
                    raise TypeError("configured system channel is not messageable")
                await channel.send(
                    MarkdownMessage(
                        title="KaosGovernor online",
                        fields=(MarkdownField("Version", __version__),),
                        bullets=("Discord transport: connected",),
                    ).render(),
                    allowed_mentions=NO_MENTIONS,
                )
            except (discord.HTTPException, TypeError):
                LOGGER.exception("Failed to send startup notification")

    async def close(self) -> None:
        if self._mail_task is not None:
            self._mail_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._mail_task
            self._mail_task = None
        await self._health.stop()
        await super().close()

    def _health_status(self) -> dict[str, object]:
        return {
            "discordReady": self.is_ready(),
            "guildId": str(self.settings.guild_id),
            "version": __version__,
            "naverMail": self.mail_poller.status(),
        }

    async def _mail_loop(self) -> None:
        loop = asyncio.get_running_loop()

        def await_discord(coroutine):
            try:
                return asyncio.run_coroutine_threadsafe(coroutine, loop).result(timeout=60)
            except Exception as exc:
                raise OSError("discord_mail_delivery_failed") from exc

        while not self.is_closed():
            await asyncio.to_thread(
                self.mail_poller.scan,
                lambda mail: await_discord(self._send_mail_summary(mail)),
                lambda attachment: await_discord(self._send_mail_attachment(attachment)),
            )
            status = self.mail_poller.status()
            if status["lastError"]:
                LOGGER.error("Naver mail scan failed: %s", status["lastError"])
            await asyncio.sleep(self.mail_poller.config.poll_seconds)

    async def _mail_channel(self) -> discord.abc.Messageable:
        channel_id = self.settings.mail_channel_id
        if channel_id is None:
            raise RuntimeError("mail_channel_not_configured")
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("mail_channel_not_messageable")
        return channel

    async def _send_mail_summary(self, mail: MailMessage):
        channel = await self._mail_channel()
        return await channel.send(
            render_mail_summary(mail, self.mail_poller.config.max_attachment_bytes),
            allowed_mentions=NO_MENTIONS,
        )

    async def _send_mail_attachment(self, attachment: Attachment):
        channel = await self._mail_channel()
        filename = safe_attachment_filename(attachment)
        return await channel.send(
            content=f"**Attachment** · {filename}",
            file=discord.File(io.BytesIO(attachment.content), filename=filename),
            allowed_mentions=NO_MENTIONS,
        )
