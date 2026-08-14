from __future__ import annotations

import asyncio
from contextlib import suppress
import io
import logging
import time

import discord
from discord import app_commands
from kaos_governor.calendar import CalendarAdapterClient, CalendarAdapterConfig
from kaos_governor.documents import PaperlessConfig, PaperlessDocumentService
from kaos_governor.mail import (
    Attachment,
    MailMessage,
    MailOrganizerConfig,
    NaverMailConfig,
    NaverMailOrganizer,
    NaverMailPoller,
)
from kaos_governor.fax import FaxConfig, FaxError, FaxService
from kaos_governor.memos import MemosConfig, MemosService

from . import __version__
from .access import AccessPolicy
from .calendar import DiscordCalendarSurface, seconds_until_next_midnight
from .config import Settings
from .health import HealthServer
from .inbox import DiscordDocumentInbox
from .fax import DiscordFaxTransport, rejection_message
from .mail import render_mail_summary, safe_attachment_filename
from .markdown import MarkdownField, MarkdownMessage, NO_MENTIONS
from .memos import DiscordMemosCapture
from .organizer import DiscordMailOrganizer
from .system_status import DiscordServiceStatusSurface
from .tasks import DiscordTasksSurface
from .tools import BrainToolServer

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
        message_intake = (
            settings.fax_message_intake
            or settings.calendar_enabled
            or settings.tasks_enabled
            or settings.supplies_enabled
            or settings.memos_enabled
            or settings.inbox_enabled
        )
        intents.guild_messages = message_intake
        intents.message_content = message_intake
        super().__init__(intents=intents, allowed_mentions=NO_MENTIONS)
        self.settings = settings
        self.policy = AccessPolicy(settings.guild_id, settings.allowed_user_ids, settings.allowed_channel_ids)
        self.tree = GovernorCommandTree(self, self.policy)
        self._started_at = time.monotonic()
        self._startup_announced = False
        self._mail_task: asyncio.Task | None = None
        self._organizer_task: asyncio.Task | None = None
        self._fax_task: asyncio.Task | None = None
        self._service_status_task: asyncio.Task | None = None
        self._calendar_midnight_task: asyncio.Task | None = None
        self._tasks_midnight_task: asyncio.Task | None = None
        self.calendar_adapter = CalendarAdapterClient(CalendarAdapterConfig(settings.calendar_adapter_url))
        self.discord_calendar = (
            DiscordCalendarSurface(
                self,
                self.policy,
                channel_id=settings.calendar_channel_id,
                profile=settings.calendar_profile,
                state_path=settings.calendar_state_path,
                adapter=self.calendar_adapter,
            )
            if settings.calendar_enabled and settings.calendar_channel_id is not None
            else None
        )
        self.discord_tasks = (
            DiscordTasksSurface(
                self,
                self.policy,
                channel_id=settings.tasks_channel_id,
                profile=settings.tasks_profile,
                state_path=settings.tasks_state_path,
                adapter=self.calendar_adapter,
            )
            if settings.tasks_enabled and settings.tasks_channel_id is not None
            else None
        )
        self.discord_supplies = (
            DiscordTasksSurface(
                self,
                self.policy,
                channel_id=settings.supplies_channel_id,
                profile=settings.supplies_profile,
                state_path=settings.supplies_state_path,
                adapter=self.calendar_adapter,
                surface_name="supplies",
                button_prefix="supplies",
                collection_id=settings.supplies_collection_id,
                show_due=False,
            )
            if settings.supplies_enabled and settings.supplies_channel_id is not None
            else None
        )
        self.paperless = PaperlessDocumentService(
            PaperlessConfig(
                base_url=settings.paperless_base_url,
                api_token=settings.paperless_api_token,
                max_document_bytes=settings.paperless_max_attachment_mb * 1024 * 1024,
                public_url=settings.paperless_public_url,
            )
        )
        self.discord_inbox = (
            DiscordDocumentInbox(
                self,
                self.policy,
                channel_id=settings.inbox_channel_id,
                state_path=settings.inbox_state_path,
                paperless=self.paperless,
            )
            if settings.inbox_enabled and settings.inbox_channel_id is not None
            else None
        )
        naver_config = NaverMailConfig.from_env()
        self.mail_poller = NaverMailPoller(naver_config)
        self.mail_organizer = NaverMailOrganizer(MailOrganizerConfig.from_env(), naver_config)
        self.discord_mail_organizer = (
            DiscordMailOrganizer(
                self,
                self.mail_organizer,
                self.policy,
                settings.mail_organizer_channel_id,
                settings.mail_archive_channel_id,
            )
            if settings.mail_organizer_channel_id is not None and settings.mail_archive_channel_id is not None
            else None
        )
        self.fax_service = FaxService(FaxConfig.from_env())
        self.memos = MemosService(MemosConfig.from_env())
        self.discord_memos = (
            DiscordMemosCapture(
                self.memos,
                self.policy,
                channel_id=settings.memos_channel_id,
            )
            if settings.memos_enabled and settings.memos_channel_id is not None
            else None
        )
        self.discord_service_status = (
            DiscordServiceStatusSurface(
                self,
                self.policy,
                channel_id=settings.service_status_channel_id,
                state_path=settings.service_status_state_path,
            )
            if settings.service_status_enabled and settings.service_status_channel_id is not None
            else None
        )
        self.discord_fax = (
            DiscordFaxTransport(
                self,
                self.fax_service,
                self.policy,
                settings.fax_archive_channel_id,
                settings.fax_notification_channel_id,
            )
            if self.fax_service.config.enabled
            and settings.fax_archive_channel_id is not None
            and settings.fax_notification_channel_id is not None
            else None
        )
        self._health = HealthServer(
            settings.health_host,
            settings.health_port,
            self._health_status,
            governor_api_token=settings.governor_api_token,
            memos=self.memos,
        )
        self._brain_tools = (
            BrainToolServer(
                settings.brain_tools_host,
                settings.brain_tools_port,
                governor_api_token=settings.governor_api_token,
                calendar_adapter=self.calendar_adapter,
                memos=self.memos,
                paperless=self.paperless,
                task_refresh_callback=self.discord_tasks.ensure_message if self.discord_tasks else None,
            )
            if settings.brain_tools_enabled
            else None
        )
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
                        f"Mail organizer: {'enabled' if self.mail_organizer.config.enabled else 'disabled'}",
                        f"Fax: {'enabled' if self.fax_service.config.enabled else 'disabled'}",
                        f"Fax message intake: {'enabled' if self.fax_service.config.message_intake else 'disabled'}",
                        f"Memos search: {'enabled' if self.memos.config.enabled else 'disabled'}",
                        f"Calendar surface: {'enabled' if self.discord_calendar is not None else 'disabled'}",
                        f"Tasks surface: {'enabled' if self.discord_tasks is not None else 'disabled'}",
                        f"Supplies surface: {'enabled' if self.discord_supplies is not None else 'disabled'}",
                        f"Memos capture: {'enabled' if self.discord_memos is not None else 'disabled'}",
                        f"Document inbox: {'enabled' if self.discord_inbox is not None else 'disabled'}",
                        f"Service status: {'enabled' if self.discord_service_status is not None else 'disabled'}",
                    ),
                    footer="Private status visible only to you",
                ).render(),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )

        @self.tree.command(name="fax-send", description="Send one PDF or image through the Kaos HylaFAX bridge")
        @app_commands.describe(destination="Domestic fax number", document="PDF or image document to send")
        async def fax_send(
            interaction: discord.Interaction,
            destination: str,
            document: discord.Attachment,
        ) -> None:
            if self.discord_fax is None:
                await interaction.response.send_message("Fax is disabled.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                job, created = await self.discord_fax.submit_attachment(
                    document,
                    destination,
                    sender=f"discord:{interaction.user.id}",
                    source_id=f"discord-interaction:{interaction.guild_id}:{interaction.channel_id}:{interaction.id}:{document.id}",
                    metadata={
                        "guildId": str(interaction.guild_id or ""),
                        "channelId": int(interaction.channel_id or 0),
                        "userId": str(interaction.user.id),
                        "attachmentId": str(document.id),
                    },
                )
            except (FaxError, discord.HTTPException) as exc:
                await interaction.edit_original_response(content=rejection_message(exc))
                return
            status = "queued" if created else "already queued"
            await interaction.edit_original_response(
                content=f"Fax {status} for {job['destination']}: {job['filename']}"
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

        @self.tree.command(name="mail-organizer-now", description="Send the Naver unread-mail organizer now")
        async def mail_organizer_now(interaction: discord.Interaction) -> None:
            if not self.mail_organizer.config.enabled or self.discord_mail_organizer is None:
                await interaction.response.send_message(
                    MarkdownMessage(title="Mail organizer disabled").render(),
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            digest = None
            try:
                digest = await asyncio.to_thread(self.mail_organizer.create_digest)
                if digest is None:
                    await asyncio.to_thread(self.mail_organizer.mark_due_sent)
                    await interaction.edit_original_response(content="No unread Naver mail. Nothing was sent.")
                    return
                await self.discord_mail_organizer.publish_digest(digest)
                await asyncio.to_thread(self.mail_organizer.mark_due_sent)
                self.mail_organizer.record_manual_digest()
                await interaction.edit_original_response(
                    content=f"Organizer sent with {len(digest.get('items', {}))} unread messages."
                )
            except Exception as exc:
                LOGGER.exception("Manual mail organizer failed")
                if digest is not None:
                    with suppress(Exception):
                        await asyncio.to_thread(self.mail_organizer.close_digest, str(digest["id"]))
                await interaction.edit_original_response(
                    content=MarkdownMessage(title="Mail organizer failed", summary=type(exc).__name__).render()
                )

        @self.tree.command(name="mail-organizer-schedule", description="Set the daily Naver organizer schedule")
        @app_commands.describe(
            runs_per_day="One or two organizer messages per day",
            first_time="First KST time in HH:MM, five-minute steps",
            second_time="Second KST time in HH:MM when runs_per_day is 2",
        )
        async def mail_organizer_schedule(
            interaction: discord.Interaction,
            runs_per_day: app_commands.Range[int, 1, 2],
            first_time: str,
            second_time: str = "17:00",
        ) -> None:
            try:
                schedule = await asyncio.to_thread(
                    self.mail_organizer.update_schedule,
                    int(runs_per_day),
                    first_time,
                    second_time,
                )
            except ValueError as exc:
                await interaction.response.send_message(
                    MarkdownMessage(title="Invalid organizer schedule", summary=str(exc)).render(),
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
                return
            await interaction.response.send_message(
                MarkdownMessage(
                    title="Mail organizer schedule",
                    fields=(
                        MarkdownField("Runs per day", schedule["runsPerDay"]),
                        MarkdownField("First", f"{schedule['firstTime']} KST"),
                        MarkdownField(
                            "Second",
                            f"{schedule['secondTime']} KST" if int(schedule["runsPerDay"]) == 2 else "Disabled",
                        ),
                    ),
                ).render(),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )

    async def setup_hook(self) -> None:
        await self._health.start()
        if self._brain_tools is not None:
            await self._brain_tools.start()
        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        LOGGER.info("Synced %d commands to guild %s", len(synced), self.settings.guild_id)

    async def on_ready(self) -> None:
        LOGGER.info("Discord ready as %s (%s)", self.user, self.user.id if self.user else None)
        if self.mail_poller.config.enabled and self._mail_task is None:
            self._mail_task = asyncio.create_task(self._mail_loop(), name="governor-naver-mail")
        if self.mail_organizer.config.enabled and self._organizer_task is None:
            if self.discord_mail_organizer is None:
                LOGGER.error("Mail organizer enabled without a Discord coordinator")
            else:
                await self.discord_mail_organizer.prune_expired()
                restored = await self.discord_mail_organizer.restore_views()
                LOGGER.info("Restored %d mail organizer views", restored)
                self._organizer_task = asyncio.create_task(
                    self._mail_organizer_loop(),
                    name="governor-naver-mail-organizer",
                )
        if self.discord_fax is not None and self._fax_task is None:
            await self.discord_fax.cycle()
            self._fax_task = asyncio.create_task(self._fax_loop(), name="governor-fax")
        if self.discord_calendar is not None:
            try:
                await self.discord_calendar.ensure_messages()
                if self._calendar_midnight_task is None:
                    self._calendar_midnight_task = asyncio.create_task(
                        self._calendar_midnight_loop(),
                        name="governor-calendar-midnight",
                    )
            except Exception:
                LOGGER.exception("Failed to ensure Discord calendar messages")
        if self.discord_tasks is not None:
            try:
                await self.discord_tasks.ensure_message()
            except Exception:
                LOGGER.exception("Failed to ensure Discord tasks message")
        if self.discord_supplies is not None:
            try:
                await self.discord_supplies.ensure_message()
            except Exception:
                LOGGER.exception("Failed to ensure Discord supplies messages")
        if (self.discord_tasks is not None or self.discord_supplies is not None) and self._tasks_midnight_task is None:
            self._tasks_midnight_task = asyncio.create_task(
                self._tasks_midnight_loop(),
                name="governor-tasks-midnight",
            )
        if self.discord_inbox is not None:
            try:
                restored = await self.discord_inbox.restore_pending_views()
                LOGGER.info("Restored %d Paperless inbox prompts", restored)
            except Exception:
                LOGGER.exception("Failed to restore Discord inbox prompts")
        if self.discord_service_status is not None:
            try:
                await self.discord_service_status.ensure_message()
                if self._service_status_task is None:
                    self._service_status_task = asyncio.create_task(
                        self._service_status_loop(),
                        name="governor-service-status",
                    )
            except Exception:
                LOGGER.exception("Failed to ensure Discord service status message")
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

    async def on_message(self, message: discord.Message) -> None:
        if self.discord_calendar is not None and await self.discord_calendar.handle_message(message):
            return
        if self.discord_tasks is not None and await self.discord_tasks.handle_message(message):
            return
        if self.discord_supplies is not None and await self.discord_supplies.handle_message(message):
            return
        if self.discord_memos is not None and await self.discord_memos.handle_message(message):
            return
        if self.discord_inbox is not None and await self.discord_inbox.handle_message(message):
            return
        if self.discord_fax is not None and self.fax_service.config.message_intake:
            await self.discord_fax.handle_message(message)

    async def close(self) -> None:
        if self._mail_task is not None:
            self._mail_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._mail_task
            self._mail_task = None
        if self._organizer_task is not None:
            self._organizer_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._organizer_task
            self._organizer_task = None
        if self._fax_task is not None:
            self._fax_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._fax_task
            self._fax_task = None
        if self._service_status_task is not None:
            self._service_status_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._service_status_task
            self._service_status_task = None
        if self._calendar_midnight_task is not None:
            self._calendar_midnight_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._calendar_midnight_task
            self._calendar_midnight_task = None
        if self._tasks_midnight_task is not None:
            self._tasks_midnight_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._tasks_midnight_task
            self._tasks_midnight_task = None
        await self._health.stop()
        if self._brain_tools is not None:
            await self._brain_tools.stop()
        await super().close()

    def _health_status(self) -> dict[str, object]:
        return {
            "discordReady": self.is_ready(),
            "guildId": str(self.settings.guild_id),
            "version": __version__,
            "brainTools": {
                "enabled": self._brain_tools is not None,
                "host": self.settings.brain_tools_host if self._brain_tools is not None else "",
                "port": self.settings.brain_tools_port if self._brain_tools is not None else 0,
            },
            "naverMail": self.mail_poller.status(),
            "naverMailOrganizer": self.mail_organizer.status(),
            "fax": self.fax_service.status(),
            "memosSearch": self.memos.status(),
            "calendarSurface": (
                self.discord_calendar.status() if self.discord_calendar is not None else {"enabled": False}
            ),
            "tasksSurface": self.discord_tasks.status() if self.discord_tasks is not None else {"enabled": False},
            "suppliesSurface": (
                self.discord_supplies.status() if self.discord_supplies is not None else {"enabled": False}
            ),
            "memosCapture": self.discord_memos.status() if self.discord_memos is not None else {"enabled": False},
            "documentInbox": self.discord_inbox.status() if self.discord_inbox is not None else {"enabled": False},
            "serviceStatus": (
                self.discord_service_status.status()
                if self.discord_service_status is not None
                else {"enabled": False}
            ),
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

    async def _mail_organizer_loop(self) -> None:
        if self.discord_mail_organizer is None:
            return
        while not self.is_closed():
            digest = None
            try:
                await self.discord_mail_organizer.prune_expired()
                digest = await asyncio.to_thread(self.mail_organizer.due_digest)
                if digest is not None:
                    await self.discord_mail_organizer.publish_digest(digest)
                await asyncio.to_thread(self.mail_organizer.mark_due_sent)
                self.mail_organizer.record_schedule_result(sent=digest is not None)
            except Exception as exc:
                LOGGER.exception("Scheduled mail organizer failed")
                self.mail_organizer.record_schedule_result(sent=False, error=exc)
                if digest is not None:
                    with suppress(Exception):
                        await asyncio.to_thread(self.mail_organizer.close_digest, str(digest["id"]))
            await asyncio.sleep(self.mail_organizer.config.scheduler_poll_seconds)

    async def _fax_loop(self) -> None:
        if self.discord_fax is None:
            return
        while not self.is_closed():
            try:
                await self.discord_fax.cycle()
            except Exception as exc:
                self.fax_service.record_error(exc)
                LOGGER.exception("Fax cycle failed")
            await asyncio.sleep(self.fax_service.config.poll_seconds)

    async def _calendar_midnight_loop(self) -> None:
        if self.discord_calendar is None:
            return
        while not self.is_closed():
            await asyncio.sleep(seconds_until_next_midnight() + 5)
            try:
                await self.discord_calendar.refresh_for_new_day()
            except Exception:
                LOGGER.exception("Failed to refresh Discord calendar for new day")

    async def _tasks_midnight_loop(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(seconds_until_next_midnight() + 10)
            for surface in (self.discord_tasks, self.discord_supplies):
                if surface is None:
                    continue
                try:
                    await surface.repost_active_messages()
                except Exception:
                    LOGGER.exception("Failed to repost Discord %s messages", surface.surface_name)

    async def _service_status_loop(self) -> None:
        if self.discord_service_status is None:
            return
        refresh_seconds = self.discord_service_status.refresh_seconds
        while not self.is_closed():
            await asyncio.sleep(refresh_seconds)
            try:
                await self.discord_service_status.ensure_message()
            except Exception:
                LOGGER.exception("Failed to refresh Discord service status message")

    async def _mail_channel(self) -> discord.abc.Messageable:
        channel_id = self.settings.mail_archive_channel_id
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
            file=discord.File(io.BytesIO(attachment.content), filename=filename),
            allowed_mentions=NO_MENTIONS,
        )
