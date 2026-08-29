from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime
import hashlib
import json
import io
import logging
from pathlib import Path
import time

import discord
from discord import app_commands
from kaos_governor.calendar import CalendarAdapterClient, CalendarAdapterConfig
from kaos_governor.daily_digest import (
    DailyDigestConfig,
    DailyDigestError,
    DailyDigestService,
    KST,
    digest_day,
    digest_events,
)
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
from kaos_governor.notifications import PushoverConfig, TextNotification, TextNotificationService

from . import __version__
from .access import AccessPolicy
from .calendar import DiscordCalendarSurface, seconds_until_next_midnight
from .config import Settings
from .health import HealthServer
from .inbox import DiscordDocumentInbox
from .fax import DiscordFaxTransport, rejection_message
from .governor_api import GovernorApiClient, GovernorApiConfig
from .mail import render_mail_summary, safe_attachment_filename
from .markdown import MarkdownField, MarkdownMessage, NO_MENTIONS
from .maintenance import (
    collect_maintenance_reports,
    due_openclaw_renewal_reminders,
    maintenance_issues,
    render_maintenance_reports,
    render_openclaw_renewal_reminder,
    render_system_maintenance_reminder,
)
from .memos import DiscordMemosCapture
from .organizer import DiscordMailOrganizer
from .system_status import DiscordServiceStatusSurface
from .tasks import DiscordTasksSurface
from .tools import BrainToolServer, ImagingSecondLookClient, ImagingSecondLookConfig

LOGGER = logging.getLogger(__name__)


def load_maintenance_reminder_state(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return set()
    return {str(item) for item in payload.get("sent", []) if str(item)}


def save_maintenance_reminder_state(path: Path, sent_keys: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps({"sent": sorted(sent_keys)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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


class DailyDigestView(discord.ui.View):
    def __init__(self, bot: "GovernorBot", day: date | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        digest_date = day or datetime.now(KST).date()
        weather = discord.ui.Button(
            label="Weather",
            style=discord.ButtonStyle.link,
            url=bot.daily_digest.weather_url(digest_date),
        )
        bible = discord.ui.Button(
            label="Bible",
            style=discord.ButtonStyle.secondary,
            custom_id="daily-digest:bible",
        )
        quote = discord.ui.Button(
            label="Quote",
            style=discord.ButtonStyle.secondary,
            custom_id="daily-digest:quote",
        )
        close = discord.ui.Button(
            label="Close",
            style=discord.ButtonStyle.secondary,
            custom_id="daily-digest:close",
        )
        bible.callback = self._bible
        quote.callback = self._quote
        close.callback = self._close
        self.add_item(weather)
        self.add_item(bible)
        self.add_item(quote)
        self.add_item(close)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.bot.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await _deny(interaction)
        return False

    async def _bible(self, interaction: discord.Interaction) -> None:
        await self.bot._cycle_daily_content(interaction, "bible")

    async def _quote(self, interaction: discord.Interaction) -> None:
        await self.bot._cycle_daily_content(interaction, "quote")

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.message is not None:
            await interaction.message.delete()


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
        self._startup_complete = False
        self._mail_task: asyncio.Task | None = None
        self._organizer_task: asyncio.Task | None = None
        self._fax_task: asyncio.Task | None = None
        self._service_status_task: asyncio.Task | None = None
        self._calendar_midnight_task: asyncio.Task | None = None
        self._tasks_midnight_task: asyncio.Task | None = None
        self._tasks_due_task: asyncio.Task | None = None
        self._tasks_refresh_task: asyncio.Task | None = None
        self._maintenance_reminder_task: asyncio.Task | None = None
        self._text_notification_task: asyncio.Task | None = None
        self._daily_digest_task: asyncio.Task | None = None
        self._daily_digest_view_message_id = 0
        self.text_notifications = TextNotificationService(PushoverConfig.from_env())
        self.calendar_adapter = CalendarAdapterClient(CalendarAdapterConfig(settings.calendar_adapter_url))
        daily_digest_config = DailyDigestConfig.from_env()
        if daily_digest_config.enabled and settings.system_channel_id is None:
            raise DailyDigestError(
                "DISCORD_SYSTEM_CHANNEL_ID is required when DAILY_DIGEST_ENABLED=true"
            )
        self.daily_digest = DailyDigestService(daily_digest_config, self.calendar_adapter)
        self.governor_api = (
            GovernorApiClient(GovernorApiConfig(settings.governor_api_url, settings.governor_api_token))
            if settings.governor_api_token
            else None
        )
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
        self.discord_task_due_notifications = (
            DiscordTasksSurface(
                self,
                self.policy,
                channel_id=settings.task_due_notification_channel_id,
                profile=settings.tasks_profile,
                state_path=settings.task_due_notification_state_path,
                adapter=self.calendar_adapter,
                messages_enabled=False,
                repeat_due_notifications=settings.task_due_repeat_notifications_enabled,
                repeat_interval_minutes=settings.task_due_repeat_interval_minutes,
            )
            if settings.task_due_notifications_enabled and settings.task_due_notification_channel_id is not None
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
                default_owner_id=settings.paperless_default_owner_id,
            )
        )
        self.discord_inbox = (
            DiscordDocumentInbox(
                self,
                self.policy,
                channel_id=settings.inbox_channel_id,
                extra_channel_ids=settings.inbox_extra_channel_ids,
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
                notification_channel_ids=frozenset(
                    channel_id
                    for channel_id in (
                        settings.system_channel_id,
                        settings.task_due_notification_channel_id,
                        settings.fax_notification_channel_id,
                    )
                    if channel_id is not None
                ),
                text_notifications=self.text_notifications,
            )
            if settings.mail_organizer_channel_id is not None and settings.mail_archive_channel_id is not None
            else None
        )
        fax_config = FaxConfig.from_env()
        self.fax_service = FaxService(fax_config)
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
                text_notifications=self.text_notifications,
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
                self.text_notifications,
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
                calendar_refresh_callback=self._refresh_calendar_surfaces,
                import_status_provider=self._import_status,
                import_items_provider=self._recent_import_items,
                fax_document_provider=self.fax_service.incoming_document,
                mail_messages_provider=lambda limit: self.mail_poller.list_messages(limit=limit),
                imaging_second_look=ImagingSecondLookClient(
                    ImagingSecondLookConfig(
                        url=settings.imaging_second_look_url,
                        token=settings.imaging_second_look_token,
                        timeout_seconds=settings.imaging_second_look_timeout_seconds,
                    )
                ),
                second_look_status_path=settings.service_status_state_path.parent / "second-look-status.json",
                second_look_status_callback=self._refresh_service_status_surface,
            )
            if settings.brain_tools_enabled
            else None
        )
        self._register_commands()

    def _import_status(self) -> dict[str, object]:
        return {
            "naverMail": self.mail_poller.status(),
            "naverMailOrganizer": self.mail_organizer.status(),
            "fax": self.fax_service.status(),
            "documentInbox": self.discord_inbox.status() if self.discord_inbox is not None else {"enabled": False},
        }

    def _recent_import_items(self) -> list[dict[str, object]]:
        return self.fax_service.recent_items(limit=50)

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
                        f"Apple Watch alerts: {'enabled' if self.text_notifications.config.enabled else 'disabled'}",
                        f"Daily digest: {'enabled' if self.daily_digest.config.enabled else 'disabled'}",
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

        @self.tree.command(name="system-refresh", description="Refresh KaosGDD system status messages now")
        async def system_refresh(interaction: discord.Interaction) -> None:
            if self.discord_service_status is None:
                await interaction.response.send_message(
                    MarkdownMessage(title="System status disabled").render(),
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                checked = await self._refresh_service_status_surface()
            except Exception as exc:
                LOGGER.exception("Manual service status refresh failed")
                await interaction.edit_original_response(
                    content=MarkdownMessage(title="System refresh failed", summary=type(exc).__name__).render()
                )
                return
            await interaction.edit_original_response(
                content=MarkdownMessage(
                    title="System status refreshed",
                    summary=f"{checked} services checked.",
                ).render()
            )

        @self.tree.command(name="maintenance-report", description="Check read-only maintenance status for KaosGDD hosts")
        async def maintenance_report(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                reports = await collect_maintenance_reports()
            except Exception as exc:
                LOGGER.exception("Maintenance report failed")
                await interaction.edit_original_response(
                    content=MarkdownMessage(title="Maintenance report failed", summary=type(exc).__name__).render()
                )
                return
            await interaction.edit_original_response(content=render_maintenance_reports(reports))

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
        self._startup_complete = False
        if self.text_notifications.config.enabled and self._text_notification_task is None:
            self._text_notification_task = asyncio.create_task(
                self._text_notification_loop(),
                name="governor-text-notifications",
            )
        if self.daily_digest.config.enabled and self._daily_digest_task is None:
            await asyncio.to_thread(self.daily_digest.initialize)
            content_status = await asyncio.to_thread(self.daily_digest.refresh_content)
            if content_status.get("lastError"):
                LOGGER.warning("Daily digest content refresh: %s", content_status["lastError"])
            last_message_id = self.daily_digest.last_message_id()
            if last_message_id and last_message_id != self._daily_digest_view_message_id:
                await self._restore_daily_digest_view(last_message_id)
            self._daily_digest_task = asyncio.create_task(
                self._daily_digest_loop(),
                name="governor-daily-digest",
            )
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
        due_task_surface = self.discord_task_due_notifications or self.discord_tasks
        if due_task_surface is not None:
            try:
                await due_task_surface.notify_due_tasks()
            except Exception:
                LOGGER.exception("Failed to send startup Discord due task notifications")
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
        if (self.discord_tasks is not None or self.discord_supplies is not None) and self._tasks_refresh_task is None:
            self._tasks_refresh_task = asyncio.create_task(
                self._tasks_refresh_loop(),
                name="governor-tasks-refresh",
            )
        if due_task_surface is not None and self._tasks_due_task is None:
            self._tasks_due_task = asyncio.create_task(
                self._tasks_due_loop(),
                name="governor-tasks-due",
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
        if self.settings.system_channel_id and self._maintenance_reminder_task is None:
            self._maintenance_reminder_task = asyncio.create_task(
                self._maintenance_reminder_loop(),
                name="governor-maintenance-reminder",
            )
        if self.settings.startup_notification and not self._startup_announced and self.settings.system_channel_id:
            self._startup_announced = True
            try:
                channel = self.get_channel(self.settings.system_channel_id) or await self.fetch_channel(self.settings.system_channel_id)
                if not isinstance(channel, discord.abc.Messageable):
                    raise TypeError("configured system channel is not messageable")
                content = MarkdownMessage(
                    title="KaosGovernor online",
                    fields=(MarkdownField("Version", __version__),),
                    bullets=("Discord transport: connected",),
                ).render()
                await channel.send(
                    content,
                    allowed_mentions=NO_MENTIONS,
                )
                await self._queue_text_notification(
                    TextNotification(
                        key=f"system:startup:{__version__}:{time.time_ns()}",
                        category="system",
                        title="",
                        message="System online.",
                    )
                )
            except (discord.HTTPException, TypeError):
                LOGGER.exception("Failed to send startup notification")
        self._startup_complete = True
        LOGGER.info("Discord startup surfaces initialized")

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
        if self._tasks_refresh_task is not None:
            self._tasks_refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._tasks_refresh_task
            self._tasks_refresh_task = None
        if self._tasks_due_task is not None:
            self._tasks_due_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._tasks_due_task
            self._tasks_due_task = None
        if self._maintenance_reminder_task is not None:
            self._maintenance_reminder_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._maintenance_reminder_task
            self._maintenance_reminder_task = None
        if self._text_notification_task is not None:
            self._text_notification_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._text_notification_task
            self._text_notification_task = None
        if self._daily_digest_task is not None:
            self._daily_digest_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._daily_digest_task
            self._daily_digest_task = None
        await self._health.stop()
        if self._brain_tools is not None:
            await self._brain_tools.stop()
        await super().close()

    def _health_status(self) -> dict[str, object]:
        return {
            "discordReady": self.is_ready(),
            "startupComplete": self._startup_complete,
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
            "textNotifications": self.text_notifications.status(),
            "dailyDigest": self.daily_digest.status(),
            "memosSearch": self.memos.status(),
            "calendarSurface": (
                self.discord_calendar.status() if self.discord_calendar is not None else {"enabled": False}
            ),
            "tasksSurface": self.discord_tasks.status() if self.discord_tasks is not None else {"enabled": False},
            "taskDueNotifications": (
                self.discord_task_due_notifications.status()
                if self.discord_task_due_notifications is not None
                else {"enabled": self.discord_tasks is not None, "messagesEnabled": self.discord_tasks is not None}
            ),
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

    async def _queue_text_notification(self, notification: TextNotification) -> bool:
        service = getattr(self, "text_notifications", None)
        if service is None or not service.config.enabled:
            return False
        try:
            return await asyncio.to_thread(service.notify, notification)
        except Exception:
            LOGGER.exception(
                "Apple Watch text alert remains queued: %s",
                notification.key,
            )
            return False

    async def _text_notification_loop(self) -> None:
        while not self.is_closed():
            try:
                await asyncio.to_thread(self.text_notifications.deliver_pending)
            except Exception:
                LOGGER.exception("Failed to deliver queued Apple Watch text alerts")
            await asyncio.sleep(self.text_notifications.config.poll_seconds)

    async def _publish_daily_digest(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(KST)
        if not self.daily_digest.is_due(current):
            return False
        channel_id = self.settings.system_channel_id
        if channel_id is None:
            raise DailyDigestError("daily_digest_channel_not_configured")
        content = await asyncio.to_thread(self.daily_digest.build, current.date())
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable) and not hasattr(channel, "send"):
            raise DailyDigestError("daily_digest_channel_not_messageable")
        message = await channel.send(
            content,
            view=DailyDigestView(self, current.date()),
            allowed_mentions=NO_MENTIONS,
        )
        await self._queue_text_notification(
            TextNotification(
                key=f"daily:{current.date().isoformat()}",
                category="daily",
                title="",
                message="Good Morning.",
            )
        )
        for event in digest_events(content):
            event_text = event.strip()
            punctuation = "" if event_text.endswith((".", "!", "?", "。", "！", "？")) else "."
            event_key = hashlib.sha256(event.encode("utf-8")).hexdigest()[:16]
            await self._queue_text_notification(
                TextNotification(
                    key=f"daily:event:{current.date().isoformat()}:{event_key}",
                    category="daily",
                    title="",
                    message=f"Today. {event_text}{punctuation}",
                )
            )
        await asyncio.to_thread(
            self.daily_digest.record_sent,
            current.date(),
            message_id=int(getattr(message, "id", 0) or 0),
        )
        self._daily_digest_view_message_id = int(getattr(message, "id", 0) or 0)
        return True

    async def _restore_daily_digest_view(self, message_id: int) -> None:
        view = DailyDigestView(self, self.daily_digest.last_sent_day())
        self.add_view(view, message_id=message_id)
        self._daily_digest_view_message_id = message_id
        channel_id = self.settings.system_channel_id
        if channel_id is None:
            return
        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if not hasattr(channel, "fetch_message"):
                raise DailyDigestError("daily_digest_channel_cannot_fetch_messages")
            message = await channel.fetch_message(message_id)
            await message.edit(view=view, allowed_mentions=NO_MENTIONS)
        except Exception:
            LOGGER.exception("Failed to refresh controls on existing daily digest message %s", message_id)

    async def _cycle_daily_content(self, interaction: discord.Interaction, kind: str) -> None:
        if interaction.message is None:
            await interaction.response.send_message(
                "Digest unavailable.",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            content = await asyncio.to_thread(
                self.daily_digest.cycle_content,
                interaction.message.content,
                kind,
            )
        except Exception as exc:
            LOGGER.exception("Failed to cycle daily digest %s", kind)
            await interaction.response.send_message(
                f"Content unavailable: {type(exc).__name__}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await interaction.response.edit_message(
            content=content,
            view=DailyDigestView(self, digest_day(content)),
            allowed_mentions=NO_MENTIONS,
        )

    async def _daily_digest_loop(self) -> None:
        next_content_check = time.monotonic() + 3600
        while not self.is_closed():
            try:
                if time.monotonic() >= next_content_check:
                    content_status = await asyncio.to_thread(self.daily_digest.refresh_content)
                    if content_status.get("lastError"):
                        LOGGER.warning("Daily digest content refresh: %s", content_status["lastError"])
                    next_content_check = time.monotonic() + 3600
                await self._publish_daily_digest()
            except Exception as exc:
                await asyncio.to_thread(self.daily_digest.record_error, exc)
                LOGGER.exception("Failed to publish daily digest")
            await asyncio.sleep(self.daily_digest.config.poll_seconds)

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

    async def _refresh_calendar_surfaces(self) -> None:
        if self.discord_calendar is not None:
            await self.discord_calendar.ensure_messages()
        if self.discord_tasks is not None:
            await self.discord_tasks.ensure_message()
        if self.discord_supplies is not None:
            await self.discord_supplies.ensure_message()

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
            synced_profiles: set[str] = set()
            for surface in (self.discord_tasks, self.discord_supplies):
                if surface is None:
                    continue
                try:
                    if surface.profile not in synced_profiles:
                        if self.governor_api is not None:
                            await asyncio.to_thread(self.governor_api.sync_recurring_tasks, surface.profile)
                        synced_profiles.add(surface.profile)
                    await surface.repost_active_messages()
                except Exception:
                    LOGGER.exception("Failed to repost Discord %s messages", surface.surface_name)

    async def _tasks_refresh_loop(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(self.settings.tasks_refresh_seconds)
            for surface in (self.discord_tasks, self.discord_supplies):
                if surface is None:
                    continue
                try:
                    await surface.ensure_message()
                except Exception:
                    LOGGER.exception("Failed to refresh Discord %s messages", surface.surface_name)

    async def _tasks_due_loop(self) -> None:
        due_task_surface = self.discord_task_due_notifications or self.discord_tasks
        if due_task_surface is None:
            return
        while not self.is_closed():
            await asyncio.sleep(60)
            try:
                await due_task_surface.notify_due_tasks()
            except Exception:
                LOGGER.exception("Failed to send Discord due task notifications")

    async def _refresh_service_status_surface(self) -> int:
        if self.discord_service_status is None:
            return 0
        await self.discord_service_status.ensure_message()
        return len(self.discord_service_status.last_results)

    async def _service_status_loop(self) -> None:
        if self.discord_service_status is None:
            return
        refresh_seconds = self.discord_service_status.refresh_seconds
        while not self.is_closed():
            await asyncio.sleep(refresh_seconds)
            try:
                await self._refresh_service_status_surface()
            except Exception:
                LOGGER.exception("Failed to refresh Discord service status message")

    async def _maintenance_reminder_loop(self) -> None:
        while not self.is_closed():
            try:
                await self._send_due_maintenance_reminders()
            except Exception:
                LOGGER.exception("Failed to send maintenance reminders")
            await asyncio.sleep(3600)

    async def _send_due_maintenance_reminders(self) -> int:
        if not self.settings.system_channel_id:
            return 0
        reports = await collect_maintenance_reports()
        reminders = due_openclaw_renewal_reminders(reports)
        issues = maintenance_issues(reports)
        issue_key = (
            f"system-maintenance:{hashlib.sha256(chr(0).join(issues).encode('utf-8')).hexdigest()[:20]}"
            if issues
            else ""
        )
        state_path = self.settings.service_status_state_path.parent / "maintenance-reminders.json"
        sent_keys = load_maintenance_reminder_state(state_path)
        pending = [reminder for reminder in reminders if reminder.key not in sent_keys]
        maintenance_pending = bool(issue_key and issue_key not in sent_keys)
        if not pending and not maintenance_pending:
            return 0
        channel = self.get_channel(self.settings.system_channel_id) or await self.fetch_channel(
            self.settings.system_channel_id
        )
        if not isinstance(channel, discord.abc.Messageable) and not hasattr(channel, "send"):
            raise TypeError("configured system channel is not messageable")
        sent_count = 0
        if maintenance_pending:
            await channel.send(render_system_maintenance_reminder(issues), allowed_mentions=NO_MENTIONS)
            await GovernorBot._queue_text_notification(
                self,
                TextNotification(
                    key=f"maintenance:{issue_key}",
                    category="maintenance",
                    title="",
                    message="System maintenance required.",
                ),
            )
            sent_keys.add(issue_key)
            sent_count += 1
        for reminder in pending:
            content = render_openclaw_renewal_reminder(reminder)
            await channel.send(content, allowed_mentions=NO_MENTIONS)
            await GovernorBot._queue_text_notification(
                self,
                TextNotification(
                    key=f"maintenance:{reminder.key}",
                    category="maintenance",
                    title="",
                    message="KaosBrain auth renewal.",
                ),
            )
            sent_keys.add(reminder.key)
            sent_count += 1
        save_maintenance_reminder_state(state_path, sent_keys)
        return sent_count

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
        sent = await channel.send(
            render_mail_summary(mail, self.mail_poller.config.max_attachment_bytes),
            allowed_mentions=NO_MENTIONS,
        )
        identity = "\0".join(
            (mail.mailbox, str(mail.uid), mail.received_at, mail.sender, mail.subject)
        )
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        await self._queue_text_notification(
            TextNotification(
                key=f"mail:message:{key}",
                category="mail",
                title="",
                message="Mail received.",
            )
        )
        return sent

    async def _send_mail_attachment(self, attachment: Attachment):
        channel = await self._mail_channel()
        filename = safe_attachment_filename(attachment)
        return await channel.send(
            file=discord.File(io.BytesIO(attachment.content), filename=filename),
            allowed_mentions=NO_MENTIONS,
        )
