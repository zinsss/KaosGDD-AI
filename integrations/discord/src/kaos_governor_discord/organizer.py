from __future__ import annotations

import asyncio
import io
import math
from typing import TYPE_CHECKING

import discord
from kaos_governor.mail import MailOrganizerError, MailMessage, NaverMailOrganizer

from .access import AccessPolicy
from .mail import render_mail_summary, safe_attachment_filename
from .markdown import MarkdownField, MarkdownMessage, NO_MENTIONS

if TYPE_CHECKING:
    from .bot import GovernorBot


PAGE_SIZE = 25


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


def render_digest(digest: dict[str, object], page: int = 0) -> str:
    items = _ordered_items(digest)
    pages = max(1, math.ceil(len(items) / PAGE_SIZE))
    page = min(max(0, page), pages - 1)
    shown = len(items)
    total = int(digest.get("totalUnread") or shown)
    fields = [
        MarkdownField("Updated", str(digest.get("createdAt") or "").replace("T", " ")[:16] + " KST"),
        MarkdownField("Unread", str(total)),
    ]
    if total > shown:
        fields.append(MarkdownField("Loaded", f"{shown} newest messages"))
    if pages > 1:
        fields.append(MarkdownField("Page", f"{page + 1} / {pages}"))
    return MarkdownMessage(
        title="Naver Mail Organizer",
        summary="Choose an unread message below.",
        fields=tuple(fields),
        footer="Naver remains authoritative",
    ).render()


def digest_options(digest: dict[str, object], page: int = 0) -> list[discord.SelectOption]:
    items = _ordered_items(digest)
    start = max(0, page) * PAGE_SIZE
    return [
        discord.SelectOption(
            label=_short(item.get("subject"), 100),
            value=item_id,
            description=_short(f"{item.get('mailboxName')} · {item.get('sender')}", 100),
        )
        for item_id, item in items[start : start + PAGE_SIZE]
    ]


class DiscordMailOrganizer:
    def __init__(
        self,
        bot: "GovernorBot",
        organizer: NaverMailOrganizer,
        policy: AccessPolicy,
        channel_id: int,
    ) -> None:
        self.bot = bot
        self.organizer = organizer
        self.policy = policy
        self.channel_id = channel_id
        self.restored = False

    async def channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("mail_channel_not_messageable")
        return channel

    async def publish_digest(self, digest: dict[str, object]) -> discord.Message:
        channel = await self.channel()
        digest_id = str(digest["id"])
        view = MailDigestView(self, digest_id, digest)
        message = await channel.send(
            render_digest(digest),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )
        self.organizer.attach_message(digest_id, self.channel_id, message.id)
        return message

    def restore_views(self) -> int:
        if self.restored:
            return 0
        count = 0
        for digest in self.organizer.active_digests():
            digest_id = str(digest.get("id") or "")
            message_id = int(digest.get("messageId") or 0)
            if digest_id and message_id:
                self.bot.add_view(MailDigestView(self, digest_id, digest), message_id=message_id)
                count += 1
        self.restored = True
        return count

    async def prune_expired(self) -> int:
        expired = await asyncio.to_thread(self.organizer.prune_digests)
        deleted = 0
        for digest in expired:
            try:
                message = await self._fetch_digest_message(digest)
                await message.delete()
                deleted += 1
            except (discord.NotFound, discord.HTTPException, RuntimeError):
                pass
        return deleted

    async def refresh_digest(self, digest_id: str) -> bool:
        digest = self.organizer.digest(digest_id)
        if not _ordered_items(digest):
            await self.delete_digest(digest_id)
            return False
        message = await self._fetch_digest_message(digest)
        await message.edit(
            content=render_digest(digest),
            view=MailDigestView(self, digest_id, digest),
            allowed_mentions=NO_MENTIONS,
        )
        return True

    async def delete_digest(self, digest_id: str) -> None:
        digest = self.organizer.close_digest(digest_id)
        try:
            message = await self._fetch_digest_message(digest)
            await message.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    async def import_item(self, digest_id: str, item_id: str) -> None:
        mail = await asyncio.to_thread(self.organizer.fetch_item, digest_id, item_id)
        progress = await asyncio.to_thread(self.organizer.import_progress, digest_id, item_id)
        channel = await self.channel()
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
                content=f"**Attachment** · {filename}",
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
        self.organizer.remove_imported(digest_id, item_id)
        await self.refresh_digest(digest_id)

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


class DigestSelect(discord.ui.Select):
    def __init__(self, parent: "MailDigestView") -> None:
        self.parent_view = parent
        options = digest_options(parent.digest, parent.page)
        super().__init__(
            placeholder="Select unread mail",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="No unread mail", value="none")],
            disabled=not options,
            custom_id=f"mail:select:{parent.digest_id}",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        item_id = self.values[0]
        await interaction.response.defer(ephemeral=True, thinking=True)
        mail = await asyncio.to_thread(
            self.parent_view.coordinator.organizer.fetch_item,
            self.parent_view.digest_id,
            item_id,
        )
        await interaction.followup.send(
            render_mail_summary(mail, self.parent_view.coordinator.organizer.naver_config.max_attachment_bytes),
            view=MailItemView(
                self.parent_view.coordinator,
                self.parent_view.digest_id,
                item_id,
                interaction.user.id,
            ),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )


class MailDigestView(RestrictedView):
    def __init__(
        self,
        coordinator: DiscordMailOrganizer,
        digest_id: str,
        digest: dict[str, object],
        page: int = 0,
    ) -> None:
        super().__init__(coordinator, timeout=None)
        self.digest_id = digest_id
        self.digest = digest
        self.pages = max(1, math.ceil(len(_ordered_items(digest)) / PAGE_SIZE))
        self.page = min(max(0, page), self.pages - 1)
        self.add_item(DigestSelect(self))
        self._add_button("Previous", discord.ButtonStyle.secondary, "prev", self._previous, self.page == 0)
        self._add_button("Next", discord.ButtonStyle.secondary, "next", self._next, self.page >= self.pages - 1)
        self._add_button("Menu", discord.ButtonStyle.primary, "menu", self._menu)
        self._add_button("Close", discord.ButtonStyle.secondary, "close", self._close)

    def _add_button(self, label, style, action, callback, disabled=False) -> None:
        button = discord.ui.Button(
            label=label,
            style=style,
            custom_id=f"mail:{action}:{self.digest_id}",
            row=1,
            disabled=disabled,
        )
        button.callback = callback
        self.add_item(button)

    async def _change_page(self, interaction: discord.Interaction, page: int) -> None:
        digest = self.coordinator.organizer.digest(self.digest_id)
        await interaction.response.edit_message(
            content=render_digest(digest, page),
            view=MailDigestView(self.coordinator, self.digest_id, digest, page),
            allowed_mentions=NO_MENTIONS,
        )

    async def _previous(self, interaction: discord.Interaction) -> None:
        await self._change_page(interaction, self.page - 1)

    async def _next(self, interaction: discord.Interaction) -> None:
        await self._change_page(interaction, self.page + 1)

    async def _menu(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            MarkdownMessage(title="Naver Mail Organizer", summary="Bulk actions apply only to this digest snapshot.").render(),
            view=MailBulkView(self.coordinator, self.digest_id, interaction.user.id),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Organizer closed.", ephemeral=True)
        await self.coordinator.delete_digest(self.digest_id)


class MailItemView(RestrictedView):
    def __init__(self, coordinator: DiscordMailOrganizer, digest_id: str, item_id: str, owner_id: int) -> None:
        super().__init__(coordinator, timeout=900, owner_id=owner_id)
        self.digest_id = digest_id
        self.item_id = item_id

    @discord.ui.button(label="Mark Read", style=discord.ButtonStyle.primary)
    async def mark_read(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(self.coordinator.organizer.mark_read, self.digest_id, self.item_id)
        await self.coordinator.refresh_digest(self.digest_id)
        await interaction.edit_original_response(content="Marked read in Naver.", view=None)
        self.stop()

    @discord.ui.button(label="Import", style=discord.ButtonStyle.success)
    async def import_mail(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.coordinator.import_item(self.digest_id, self.item_id)
        await interaction.edit_original_response(content="Imported to Discord. Naver read state was unchanged.", view=None)
        self.stop()

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=MarkdownMessage(title="Delete this mail?", summary="The message will move to Naver Trash.").render(),
            view=MailDeleteConfirmationView(
                self.coordinator,
                self.digest_id,
                self.item_id,
                interaction.user.id,
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Closed.", view=None)
        self.stop()


class MailDeleteConfirmationView(RestrictedView):
    def __init__(self, coordinator, digest_id: str, item_id: str, owner_id: int) -> None:
        super().__init__(coordinator, timeout=60, owner_id=owner_id)
        self.digest_id = digest_id
        self.item_id = item_id

    @discord.ui.button(label="Delete from Naver", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(self.coordinator.organizer.delete, self.digest_id, self.item_id)
        await self.coordinator.refresh_digest(self.digest_id)
        await interaction.edit_original_response(content="Moved to Naver Trash.", view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Delete cancelled.", view=None)
        self.stop()


class MailBulkView(RestrictedView):
    def __init__(self, coordinator, digest_id: str, owner_id: int) -> None:
        super().__init__(coordinator, timeout=300, owner_id=owner_id)
        self.digest_id = digest_id

    @discord.ui.button(label="Mark Read All", style=discord.ButtonStyle.primary)
    async def mark_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(self.coordinator.organizer.mark_read_all, self.digest_id)
        await self.coordinator.refresh_digest(self.digest_id)
        await interaction.edit_original_response(content="Digest messages marked read in Naver.", view=None)
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
        await interaction.response.edit_message(content="Closed.", view=None)
        self.stop()


class MailDeleteAllConfirmationView(RestrictedView):
    def __init__(self, coordinator, digest_id: str, owner_id: int) -> None:
        super().__init__(coordinator, timeout=60, owner_id=owner_id)
        self.digest_id = digest_id

    @discord.ui.button(label="Delete Snapshot", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(self.coordinator.organizer.delete_all, self.digest_id)
        await self.coordinator.refresh_digest(self.digest_id)
        await interaction.edit_original_response(content="Digest messages moved to Naver Trash.", view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Delete cancelled.", view=None)
        self.stop()
