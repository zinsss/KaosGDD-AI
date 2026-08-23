from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime
import io
import logging
from typing import TYPE_CHECKING

import discord
from kaos_governor.mail import MailOrganizerError, MailMessage, NaverMailOrganizer

from .access import AccessPolicy
from .mail import render_mail_summary, safe_attachment_filename
from .markdown import MarkdownField, MarkdownMessage, NO_MENTIONS

if TYPE_CHECKING:
    from .bot import GovernorBot

LOGGER = logging.getLogger(__name__)


def _ordered_items(digest: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    items = digest.get("items", {})
    if not isinstance(items, dict):
        return []
    order = [item_id for item_id in digest.get("order", []) if item_id in items]
    order.extend(item_id for item_id in items if item_id not in order)
    return [(item_id, items[item_id]) for item_id in order]


def _short(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split()) or "(No subject)"
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _digest_date(digest: dict[str, object]) -> date | None:
    created_at = str(digest.get("createdAt") or "").strip()
    if created_at:
        with suppress(ValueError):
            return datetime.fromisoformat(created_at).date()
    created_epoch = digest.get("createdEpoch")
    if isinstance(created_epoch, (int, float)):
        with suppress(OSError, ValueError):
            return datetime.fromtimestamp(float(created_epoch)).date()
    return None


def render_digest(digest: dict[str, object]) -> str:
    items = _ordered_items(digest)
    shown = len(items)
    total = int(digest.get("totalUnread") or shown)
    fields = [
        MarkdownField("Updated", str(digest.get("createdAt") or "").replace("T", " ")[:16] + " KST"),
        MarkdownField("Unread", str(total)),
    ]
    if total > shown:
        fields.append(MarkdownField("Loaded", f"{shown} newest messages"))
    return MarkdownMessage(
        title="Naver Mail Organizer",
        summary="Use the direct actions on each unread message below.",
        fields=tuple(fields),
        footer="Naver remains authoritative",
    ).render()


def render_digest_item(item: dict[str, object]) -> str:
    subject = _short(item.get("subject"), 300)
    context = _short(f"{item.get('mailboxName')} · {item.get('sender')}", 500)
    escaped_subject = discord.utils.escape_markdown(discord.utils.escape_mentions(subject))
    escaped_context = discord.utils.escape_markdown(discord.utils.escape_mentions(context))
    return f"**{escaped_subject}**\n-# {escaped_context}"


class DiscordMailOrganizer:
    def __init__(
        self,
        bot: "GovernorBot",
        organizer: NaverMailOrganizer,
        policy: AccessPolicy,
        channel_id: int,
        archive_channel_id: int,
    ) -> None:
        self.bot = bot
        self.organizer = organizer
        self.policy = policy
        self.channel_id = channel_id
        self.archive_channel_id = archive_channel_id
        self.restored = False

    async def channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("mail_channel_not_messageable")
        return channel

    async def archive_channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.archive_channel_id) or await self.bot.fetch_channel(self.archive_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("mail_archive_channel_not_messageable")
        return channel

    async def publish_digest(self, digest: dict[str, object]) -> discord.Message:
        channel = await self.channel()
        digest_id = str(digest["id"])
        try:
            await self.delete_previous_day_digests(digest)
            message = await channel.send(
                render_digest(digest),
                view=MailDigestView(self, digest_id),
                allowed_mentions=NO_MENTIONS,
            )
            await asyncio.to_thread(
                self.organizer.attach_message,
                digest_id,
                self.channel_id,
                message.id,
            )
            for item_id, item in _ordered_items(digest):
                await self._publish_item(channel, digest_id, item_id, item)
            return message
        except Exception:
            await self.delete_digest(digest_id)
            raise

    async def restore_views(self) -> int:
        if self.restored:
            return 0
        count = 0
        for digest in self.organizer.active_digests():
            digest_id = str(digest.get("id") or "")
            message_id = int(digest.get("messageId") or 0)
            if digest_id and message_id:
                self.bot.add_view(MailDigestView(self, digest_id), message_id=message_id)
                count += 1
                channel = await self.channel()
                for item_id, item in _ordered_items(digest):
                    item_message_id = int(item.get("organizerMessageId") or 0)
                    if item_message_id:
                        self.bot.add_view(
                            MailItemActionView(self, digest_id, item_id),
                            message_id=item_message_id,
                        )
                    else:
                        await self._publish_item(channel, digest_id, item_id, item)
                    count += 1
        self.restored = True
        return count

    async def prune_expired(self) -> int:
        expired = await asyncio.to_thread(self.organizer.prune_digests)
        deleted = 0
        for digest in expired:
            deleted += await self._delete_digest_messages(digest)
        return deleted

    async def delete_previous_day_digests(self, digest: dict[str, object]) -> int:
        current_date = _digest_date(digest)
        if current_date is None:
            return 0
        deleted = 0
        for existing in await asyncio.to_thread(self.organizer.active_digests):
            existing_id = str(existing.get("id") or "")
            existing_date = _digest_date(existing)
            if not existing_id or existing_id == str(digest.get("id") or "") or existing_date is None:
                continue
            if existing_date >= current_date:
                continue
            try:
                await self.delete_digest(existing_id)
                deleted += 1
            except Exception as exc:
                LOGGER.warning("Failed to delete stale mail organizer digest id=%s: %s", existing_id, exc)
        return deleted

    async def refresh_digest(self, digest_id: str) -> bool:
        digest = self.organizer.digest(digest_id)
        if not _ordered_items(digest):
            await self.delete_digest(digest_id)
            return False
        message = await self._fetch_digest_message(digest)
        await message.edit(
            content=render_digest(digest),
            view=MailDigestView(self, digest_id),
            allowed_mentions=NO_MENTIONS,
        )
        return True

    async def delete_digest(self, digest_id: str) -> None:
        digest = await asyncio.to_thread(self.organizer.close_digest, digest_id)
        await self._delete_digest_messages(digest)

    async def import_item(self, digest_id: str, item_id: str) -> None:
        mail = await asyncio.to_thread(self.organizer.fetch_item, digest_id, item_id)
        progress = await asyncio.to_thread(self.organizer.import_progress, digest_id, item_id)
        channel = await self.archive_channel()
        if not progress.get("summaryMessageId"):
            summary = await channel.send(
                render_mail_summary(mail, self.organizer.naver_config.max_attachment_bytes),
                allowed_mentions=NO_MENTIONS,
            )
            await asyncio.to_thread(
                self.organizer.mark_import_summary,
                digest_id,
                item_id,
                summary.id,
            )
        uploaded = set(progress.get("uploadedAttachments") or [])
        for index, attachment in enumerate(mail.attachments):
            key = f"{index}:{attachment.filename}:{len(attachment.content)}"
            if key in uploaded or not attachment.content or len(attachment.content) > self.organizer.naver_config.max_attachment_bytes:
                continue
            filename = safe_attachment_filename(attachment)
            await channel.send(
                file=discord.File(io.BytesIO(attachment.content), filename=filename),
                allowed_mentions=NO_MENTIONS,
            )
            await asyncio.to_thread(
                self.organizer.mark_import_attachment,
                digest_id,
                item_id,
                key,
            )
            uploaded.add(key)
        await asyncio.to_thread(self.organizer.remove_imported, digest_id, item_id)

    async def delete_item_message(self, message_id: int) -> None:
        channel = await self.channel()
        if not hasattr(channel, "fetch_message"):
            raise RuntimeError("mail_channel_not_messageable")
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    async def delete_item_messages(self, digest: dict[str, object]) -> int:
        deleted = 0
        for _item_id, item in _ordered_items(digest):
            message_id = int(item.get("organizerMessageId") or 0)
            if not message_id:
                continue
            try:
                await self.delete_item_message(message_id)
                deleted += 1
            except (discord.HTTPException, RuntimeError):
                pass
        return deleted

    async def _publish_item(
        self,
        channel: discord.abc.Messageable,
        digest_id: str,
        item_id: str,
        item: dict[str, object],
    ) -> discord.Message:
        message = await channel.send(
            render_digest_item(item),
            view=MailItemActionView(self, digest_id, item_id),
            allowed_mentions=NO_MENTIONS,
        )
        await asyncio.to_thread(
            self.organizer.attach_item_message,
            digest_id,
            item_id,
            message.id,
        )
        return message

    async def _delete_digest_messages(self, digest: dict[str, object]) -> int:
        deleted = await self.delete_item_messages(digest)
        try:
            message = await self._fetch_digest_message(digest)
            await message.delete()
            deleted += 1
        except (discord.NotFound, discord.HTTPException, RuntimeError):
            pass
        return deleted

    async def _fetch_digest_message(self, digest: dict[str, object]) -> discord.Message:
        channel_id = int(digest.get("channelId") or self.channel_id)
        message_id = int(digest.get("messageId") or 0)
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not hasattr(channel, "fetch_message"):
            raise RuntimeError("mail_channel_not_messageable")
        return await channel.fetch_message(message_id)


class RestrictedView(discord.ui.View):
    def __init__(self, coordinator: DiscordMailOrganizer, *, timeout: float | None, owner_id: int | None = None) -> None:
        super().__init__(timeout=timeout)
        self.coordinator = coordinator
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed = self.coordinator.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id)
        if self.owner_id is not None:
            allowed = allowed and interaction.user.id == self.owner_id
        if allowed:
            return True
        message = MarkdownMessage(title="Access denied").render()
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message(message, ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        code = str(error) if isinstance(error, MailOrganizerError) else type(error).__name__
        message = MarkdownMessage(title="Mail action failed", summary=code).render()
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message(message, ephemeral=True, allowed_mentions=NO_MENTIONS)


class MailDigestView(RestrictedView):
    def __init__(self, coordinator: DiscordMailOrganizer, digest_id: str) -> None:
        super().__init__(coordinator, timeout=None)
        self.digest_id = digest_id
        self._add_button("Menu", discord.ButtonStyle.primary, "menu", self._menu)
        self._add_button("Close", discord.ButtonStyle.secondary, "close", self._close)

    def _add_button(self, label, style, action, callback) -> None:
        button = discord.ui.Button(
            label=label,
            style=style,
            custom_id=f"mail:{action}:{self.digest_id}",
            row=0,
        )
        button.callback = callback
        self.add_item(button)

    async def _menu(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            MarkdownMessage(title="Naver Mail Organizer", summary="Bulk actions apply only to this digest snapshot.").render(),
            view=MailBulkView(self.coordinator, self.digest_id, interaction.user.id),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.coordinator.delete_digest(self.digest_id)
        await delete_ephemeral_response(interaction)


class MailItemActionView(RestrictedView):
    def __init__(self, coordinator: DiscordMailOrganizer, digest_id: str, item_id: str) -> None:
        super().__init__(coordinator, timeout=None)
        self.digest_id = digest_id
        self.item_id = item_id
        self._add_button("Import", discord.ButtonStyle.success, "import", self._import)
        self._add_button("Mark Read", discord.ButtonStyle.primary, "read", self._mark_read)
        self._add_button("Delete", discord.ButtonStyle.danger, "delete", self._delete)

    def _add_button(self, label, style, action, callback) -> None:
        button = discord.ui.Button(
            label=label,
            style=style,
            custom_id=f"mail:item:{action}:{self.digest_id}:{self.item_id}",
        )
        button.callback = callback
        self.add_item(button)

    async def _mark_read(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await asyncio.to_thread(self.coordinator.organizer.mark_read, self.digest_id, self.item_id)
        await self.coordinator.delete_item_message(interaction.message.id)
        await self.coordinator.refresh_digest(self.digest_id)
        await delete_ephemeral_response(interaction)
        self.stop()

    async def _import(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.coordinator.import_item(self.digest_id, self.item_id)
        await self.coordinator.delete_item_message(interaction.message.id)
        await self.coordinator.refresh_digest(self.digest_id)
        await delete_ephemeral_response(interaction)
        self.stop()

    async def _delete(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            content=MarkdownMessage(title="Delete this mail?", summary="The message will move to Naver Trash.").render(),
            view=MailDeleteConfirmationView(
                self.coordinator,
                self.digest_id,
                self.item_id,
                interaction.user.id,
                interaction.message.id,
            ),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )


class MailDeleteConfirmationView(RestrictedView):
    def __init__(
        self,
        coordinator,
        digest_id: str,
        item_id: str,
        owner_id: int,
        organizer_message_id: int,
    ) -> None:
        super().__init__(coordinator, timeout=60, owner_id=owner_id)
        self.digest_id = digest_id
        self.item_id = item_id
        self.organizer_message_id = organizer_message_id

    @discord.ui.button(label="Delete from Naver", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(self.coordinator.organizer.delete, self.digest_id, self.item_id)
        await self.coordinator.delete_item_message(self.organizer_message_id)
        await self.coordinator.refresh_digest(self.digest_id)
        await delete_ephemeral_response(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await delete_ephemeral_response(interaction)
        self.stop()


class MailBulkView(RestrictedView):
    def __init__(self, coordinator, digest_id: str, owner_id: int) -> None:
        super().__init__(coordinator, timeout=300, owner_id=owner_id)
        self.digest_id = digest_id

    @discord.ui.button(label="Mark Read All", style=discord.ButtonStyle.primary)
    async def mark_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        digest = await asyncio.to_thread(self.coordinator.organizer.digest, self.digest_id)
        await asyncio.to_thread(self.coordinator.organizer.mark_read_all, self.digest_id)
        await self.coordinator.delete_item_messages(digest)
        await self.coordinator.refresh_digest(self.digest_id)
        await delete_ephemeral_response(interaction)
        self.stop()

    @discord.ui.button(label="Delete All", style=discord.ButtonStyle.danger)
    async def delete_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=MarkdownMessage(
                title="Delete all messages in this digest?",
                summary="Only this saved digest snapshot will move to Naver Trash.",
            ).render(),
            view=MailDeleteAllConfirmationView(self.coordinator, self.digest_id, interaction.user.id),
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await delete_ephemeral_response(interaction)
        self.stop()


class MailDeleteAllConfirmationView(RestrictedView):
    def __init__(self, coordinator, digest_id: str, owner_id: int) -> None:
        super().__init__(coordinator, timeout=60, owner_id=owner_id)
        self.digest_id = digest_id

    @discord.ui.button(label="Delete Snapshot", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        digest = await asyncio.to_thread(self.coordinator.organizer.digest, self.digest_id)
        await asyncio.to_thread(self.coordinator.organizer.delete_all, self.digest_id)
        await self.coordinator.delete_item_messages(digest)
        await self.coordinator.refresh_digest(self.digest_id)
        await delete_ephemeral_response(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await delete_ephemeral_response(interaction)
        self.stop()


async def delete_ephemeral_response(interaction: discord.Interaction) -> None:
    with suppress(discord.HTTPException):
        await interaction.delete_original_response()
