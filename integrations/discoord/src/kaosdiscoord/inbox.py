from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import discord
from kaos_governor.documents import (
    DocumentIntakeError,
    PaperlessDocumentService,
)

from .access import AccessPolicy
from .fax import safe_filename
from .inbox_formatting import (
    attachment_display_filename,
    degraded_discord_filename,
    extract_korean_name_from_document,
    generated_discord_filename,
    infer_pdf_title,
    keyword_document_tags,
    merge_tags,
    metadata_instruction,
    normalize_inferred_title,
    paperless_document_link,
    paperless_result_line,
    parse_metadata_reply,
    parse_tag_text,
    read_attachment_bytes,
    record_display_filename,
    rejection_message,
    render_metadata_message,
    render_ocr_done_message,
    render_ocr_pending_message,
    render_ocr_ready_message,
    render_paperless_browse_summary,
    render_paperless_opened,
    render_paperless_search,
    render_paperless_search_expired,
    render_paperless_search_summary,
    render_pending_message,
    render_processing_message,
    render_submitted_message,
    suggest_document_tags,
)
from .markdown import NO_MENTIONS, escape_text
from .paperless_search_view import PaperlessSearchView
from .search import normalize_dotdot_query


LOGGER = logging.getLogger(__name__)


@dataclass
class InboxRecord:
    source_id: str
    sha256: str
    filename: str
    task_id: str
    message_id: int
    document_id: int = 0
    prompt_message_id: int = 0
    title: str = ""
    tags: tuple[str, ...] = ()


@dataclass
class PendingDocument:
    source_id: str
    channel_id: int
    message_id: int
    attachment_id: int
    prompt_message_id: int
    author_id: int
    sha256: str
    filename: str


@dataclass
class DiscordInboxState:
    sources: dict[str, InboxRecord] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)
    pending: dict[str, PendingDocument] = field(default_factory=dict)


class DiscordDocumentInbox:
    def __init__(
        self,
        bot: discord.Client,
        policy: AccessPolicy,
        *,
        channel_id: int,
        extra_channel_ids: frozenset[int] = frozenset(),
        state_path: Path,
        paperless: PaperlessDocumentService,
    ) -> None:
        self.bot = bot
        self.policy = policy
        self.channel_id = channel_id
        self.channel_ids = frozenset({channel_id, *extra_channel_ids})
        self.state_path = state_path
        self.paperless = paperless
        self.state = self._load_state()
        self.accepted_count = 0
        self.duplicate_count = 0
        self.rejected_count = 0
        self.ocr_ready_count = 0
        self.ocr_pending_count = 0
        self.last_error = ""

    async def handle_message(self, message: discord.Message) -> bool:
        if message.channel.id not in self.channel_ids:
            return False
        if message.author.bot:
            return self._is_own_message(message)
        if not self.policy.allows(message.guild.id if message.guild else None, message.channel.id, message.author.id):
            LOGGER.warning("Rejected inbox message channel=%s user=%s", message.channel.id, message.author.id)
            return False
        if await self._handle_metadata_reply(message):
            return True
        if not message.attachments:
            return False
        if len(message.attachments) != 1:
            await message.reply(
                "Upload one PDF file per message.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return True

        attachment = message.attachments[0]
        try:
            result = await self.prepare_attachment(message, attachment)
            if result["duplicate"]:
                self.duplicate_count += 1
                await message.reply(
                    f"## Documents\n- {escape_text(result['filename'])}: already submitted",
                    mention_author=False,
                    allowed_mentions=NO_MENTIONS,
                )
            else:
                prompt = await message.reply(
                    render_pending_message(str(result["filename"])),
                    mention_author=False,
                    allowed_mentions=NO_MENTIONS,
                    view=InboxMenuView(self, str(result["sourceId"])),
                )
                if getattr(prompt, "id", 0):
                    pending = self.state.pending[str(result["sourceId"])]
                    pending.prompt_message_id = int(prompt.id)
                    self._save_state()
        except (DocumentIntakeError, discord.HTTPException) as exc:
            self.rejected_count += 1
            self.last_error = str(exc)
            await message.reply(
                f"## Documents\n- {escape_text(attachment_display_filename(attachment))}: {escape_text(rejection_message(exc))}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
        return True

    async def prepare_attachment(self, message: discord.Message, attachment: discord.Attachment) -> dict[str, Any]:
        if not attachment.filename.lower().endswith(".pdf"):
            raise DocumentIntakeError("pdf_attachment_required")
        if attachment.size <= 0 or attachment.size > self.paperless.config.max_document_bytes:
            raise DocumentIntakeError("pdf_size_invalid")
        source_id = f"discord:{message.guild.id}:{message.channel.id}:{message.id}:{attachment.id}"
        if source_id in self.state.sources:
            record = self.state.sources[source_id]
            return {
                "duplicate": True,
                "filename": record_display_filename(record),
                "taskId": record.task_id,
                "sha256": record.sha256,
            }
        if source_id in self.state.pending:
            pending = self.state.pending[source_id]
            return {
                "duplicate": False,
                "filename": pending.filename,
                "sourceId": pending.source_id,
                "sha256": pending.sha256,
            }
        content = await read_attachment_bytes(attachment)
        if not content.startswith(b"%PDF-"):
            raise DocumentIntakeError("invalid_pdf_signature")
        digest = hashlib.sha256(content).hexdigest()
        if digest in self.state.hashes:
            source = self.state.hashes[digest]
            record = self.state.sources[source]
            self.state.sources[source_id] = replace(record, source_id=source_id, message_id=int(message.id))
            self._save_state()
            return {
                "duplicate": True,
                "filename": record_display_filename(record),
                "taskId": record.task_id,
                "sha256": record.sha256,
            }
        filename = attachment_display_filename(attachment)
        if degraded_discord_filename(filename):
            inferred_title = infer_pdf_title(content)
            if inferred_title:
                filename = safe_filename(f"{inferred_title}.pdf")
        pending = PendingDocument(
            source_id=source_id,
            channel_id=int(message.channel.id),
            message_id=int(message.id),
            attachment_id=int(attachment.id),
            prompt_message_id=0,
            author_id=int(message.author.id),
            sha256=digest,
            filename=filename,
        )
        self.state.pending[source_id] = pending
        self._save_state()
        self.last_error = ""
        return {
            "duplicate": False,
            "filename": pending.filename,
            "sourceId": source_id,
            "sha256": digest,
        }

    async def process_pending(self, source_id: str, *, title: str = "", tags: tuple[str, ...] = ()) -> InboxRecord:
        pending = self.state.pending.get(source_id)
        if pending is None:
            raise DocumentIntakeError("paperless_pending_missing")
        channel = self.bot.get_channel(pending.channel_id) or await self.bot.fetch_channel(pending.channel_id)
        if not hasattr(channel, "fetch_message"):
            raise DocumentIntakeError("paperless_source_unavailable")
        source_message = await channel.fetch_message(pending.message_id)
        attachment = next((item for item in source_message.attachments if int(item.id) == pending.attachment_id), None)
        if attachment is None:
            raise DocumentIntakeError("paperless_attachment_missing")
        content = await read_attachment_bytes(attachment)
        digest = hashlib.sha256(content).hexdigest()
        if digest != pending.sha256:
            raise DocumentIntakeError("paperless_attachment_changed")
        if digest in self.state.hashes:
            record = self.state.sources[self.state.hashes[digest]]
            self.state.sources[source_id] = replace(record, source_id=source_id, message_id=pending.message_id)
            self.state.pending.pop(source_id, None)
            self._save_state()
            return record
        attachment_filename = attachment_display_filename(attachment)
        submit_filename = attachment_filename if not degraded_discord_filename(attachment_filename) else pending.filename
        if degraded_discord_filename(submit_filename):
            if not title:
                title = infer_pdf_title(content)
            if title:
                submit_filename = safe_filename(f"{title}.pdf")
        submit_title = title or Path(submit_filename).stem
        result = await asyncio.to_thread(
            self.paperless.submit_pdf,
            submit_filename,
            content,
            title=submit_title,
            tags=tags,
            source="discord",
        )
        record = InboxRecord(
            source_id=source_id,
            sha256=result.sha256,
            filename=result.filename,
            task_id=result.task_id,
            message_id=pending.message_id,
            prompt_message_id=pending.prompt_message_id,
            title=submit_title,
            tags=tags,
        )
        self.state.sources[source_id] = record
        self.state.hashes[result.sha256] = source_id
        self.state.pending.pop(source_id, None)
        self._save_state()
        self.accepted_count += 1
        self.last_error = ""
        return record

    async def close_pending(self, source_id: str) -> bool:
        removed = self.state.pending.pop(source_id, None)
        if removed is None:
            return False
        self._save_state()
        return True

    async def restore_pending_views(self) -> int:
        restored = 0
        for source_id, pending in list(self.state.pending.items()):
            if not pending.prompt_message_id:
                continue
            try:
                channel = self.bot.get_channel(pending.channel_id) or await self.bot.fetch_channel(pending.channel_id)
                if not hasattr(channel, "fetch_message"):
                    continue
                message = await channel.fetch_message(pending.prompt_message_id)
                view = InboxMenuView(self, source_id)
                await message.edit(
                    content=render_pending_message(pending.filename),
                    view=view,
                    allowed_mentions=NO_MENTIONS,
                )
                self._register_view(view, int(message.id))
                restored += 1
            except discord.HTTPException:
                LOGGER.info("Could not restore Paperless inbox prompt %s", pending.prompt_message_id)
        return restored

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "channelIds": [str(channel_id) for channel_id in sorted(self.channel_ids)],
            "acceptedCount": self.accepted_count,
            "duplicateCount": self.duplicate_count,
            "rejectedCount": self.rejected_count,
            "ocrReadyCount": self.ocr_ready_count,
            "ocrPendingCount": self.ocr_pending_count,
            "pendingCount": len(self.state.pending),
            "trackedSources": len(self.state.sources),
            "trackedHashes": len(self.state.hashes),
            "lastError": self.last_error,
            "paperless": self.paperless.status(),
        }

    async def _handle_search(self, message: discord.Message, query: str) -> None:
        raw_query = " ".join(str(query or "").split())
        if not raw_query or (raw_query.casefold() == "all" and raw_query != "ALL"):
            await self._delete_message(message)
            await message.channel.send(
                "Use `..ALL` to browse all documents.",
                allowed_mentions=NO_MENTIONS,
            )
            return
        browse_all = raw_query == "ALL"
        normalized_query = "" if browse_all else normalize_dotdot_query(raw_query)
        try:
            if browse_all:
                page = await asyncio.to_thread(self.paperless.list_page, limit=25)
            else:
                page = await asyncio.to_thread(self.paperless.search_page, normalized_query, limit=25)
        except DocumentIntakeError as exc:
            self.rejected_count += 1
            self.last_error = exc.code
            await message.reply(
                f"Documents search rejected: {escape_text(rejection_message(exc))}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        except Exception:
            self.rejected_count += 1
            self.last_error = "internal_error"
            LOGGER.exception("Unexpected Paperless search failure")
            await message.reply(
                "Documents search rejected: internal_error",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await self._delete_message(message)
        content = render_paperless_search_summary(page, public_url=self.paperless.config.public_url)
        view = PaperlessSearchView(self, page, self.policy, public_url=self.paperless.config.public_url) if page.results else None
        sent = await message.channel.send(
            content,
            view=view,
            allowed_mentions=NO_MENTIONS,
        )
        if view is not None:
            view.bind_message(sent)
        self.last_error = ""

    async def _handle_metadata_reply(self, message: discord.Message) -> bool:
        reference = getattr(message, "reference", None)
        prompt_message_id = int(getattr(reference, "message_id", 0) or 0)
        if not prompt_message_id:
            return False
        pending = next(
            (item for item in self.state.pending.values() if item.prompt_message_id == prompt_message_id),
            None,
        )
        if pending is None:
            return False
        metadata = parse_metadata_reply(message.content)
        if metadata is None:
            await message.reply(
                metadata_instruction(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return True
        title, tags = metadata
        try:
            await self._edit_prompt(
                pending,
                render_processing_message(pending.filename),
                view=None,
            )
            record = await self.process_pending(pending.source_id, title=title, tags=tags)
            await self._edit_prompt(
                pending,
                render_submitted_message(record),
                view=InboxClosedView(),
            )
            self.track_ocr(record)
        except (DocumentIntakeError, discord.HTTPException) as exc:
            self.rejected_count += 1
            self.last_error = str(exc)
            await message.reply(
                f"Documents import failed: {escape_text(rejection_message(exc))}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
        return True

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete Paperless search message %s", getattr(message, "id", ""))

    async def _edit_prompt(
        self,
        pending: PendingDocument,
        content: str,
        *,
        view: discord.ui.View | None,
    ) -> None:
        if not pending.prompt_message_id:
            return
        channel = self.bot.get_channel(pending.channel_id) or await self.bot.fetch_channel(pending.channel_id)
        if not hasattr(channel, "fetch_message"):
            return
        message = await channel.fetch_message(pending.prompt_message_id)
        await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
        self._register_view(view, int(message.id))

    def track_ocr(self, record: InboxRecord) -> None:
        if not record.task_id or not record.prompt_message_id:
            return
        asyncio.create_task(self._track_ocr(record.source_id))

    async def _track_ocr(self, source_id: str) -> None:
        for attempt in range(30):
            record = self.state.sources.get(source_id)
            if record is None or not record.task_id:
                return
            try:
                task = await asyncio.to_thread(self.paperless.task, record.task_id)
                if not task.done:
                    await asyncio.sleep(10)
                    continue
                if not task.success or not task.related_document_ids:
                    self.ocr_pending_count += 1
                    await self._edit_record_prompt(record, render_ocr_pending_message(record))
                    return
                document = await asyncio.to_thread(self.paperless.get, task.related_document_ids[0])
                tags = merge_tags(record.tags, suggest_document_tags(document))
                updated = replace(record, document_id=document.document_id, title=document.title or record.title, tags=tags)
                if tags != record.tags:
                    document = await asyncio.to_thread(
                        self.paperless.update_metadata,
                        document.document_id,
                        title=updated.title,
                        tags=tags,
                    )
                    updated = replace(updated, title=document.title or updated.title, document_id=document.document_id)
                self.state.sources[source_id] = updated
                self._save_state()
                if not str(document.content or "").strip():
                    await asyncio.sleep(10)
                    continue
                self.ocr_ready_count += 1
                await self._edit_record_prompt(updated, render_ocr_ready_message(updated, document.title))
                return
            except (DocumentIntakeError, discord.HTTPException) as exc:
                self.last_error = str(exc)
                LOGGER.info("Paperless OCR tracking not ready source=%s attempt=%s error=%s", source_id, attempt + 1, exc)
                await asyncio.sleep(10)
            except Exception:
                self.last_error = "internal_error"
                LOGGER.exception("Unexpected Paperless OCR tracking failure source=%s", source_id)
                return
        record = self.state.sources.get(source_id)
        if record is not None:
            self.ocr_pending_count += 1
            await self._edit_record_prompt(record, render_ocr_pending_message(record))

    async def _edit_record_prompt(self, record: InboxRecord, content: str) -> None:
        if not record.prompt_message_id:
            return
        channel_id = self.channel_id
        parts = record.source_id.split(":")
        if len(parts) >= 3:
            try:
                channel_id = int(parts[2])
            except ValueError:
                channel_id = self.channel_id
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not hasattr(channel, "fetch_message"):
            return
        message = await channel.fetch_message(record.prompt_message_id)
        view = OcrReadyView(self, record.source_id) if record.document_id else InboxClosedView()
        await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)

    async def update_record_metadata(self, source_id: str, *, title: str, tags: tuple[str, ...]) -> InboxRecord:
        record = self.state.sources.get(source_id)
        if record is None or record.document_id <= 0:
            raise DocumentIntakeError("paperless_document_missing")
        document = await asyncio.to_thread(
            self.paperless.update_metadata,
            record.document_id,
            title=title,
            tags=tags,
        )
        updated = replace(
            record,
            title=document.title,
            tags=tuple(tags),
            document_id=document.document_id,
        )
        self.state.sources[source_id] = updated
        self._save_state()
        return updated

    def _register_view(self, view: discord.ui.View | None, message_id: int) -> None:
        if view is None or not hasattr(self.bot, "add_view"):
            return
        try:
            self.bot.add_view(view, message_id=message_id)
        except ValueError:
            LOGGER.info("Could not register persistent Documents inbox view for message %s", message_id)

    def _load_state(self) -> DiscordInboxState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DiscordInboxState()
        if not isinstance(raw, dict):
            return DiscordInboxState()
        sources = {}
        for key, value in dict(raw.get("sources") or {}).items():
            if not isinstance(value, dict):
                continue
            record = InboxRecord(
                source_id=str(value.get("sourceId") or key),
                sha256=str(value.get("sha256") or ""),
                filename=str(value.get("filename") or "document.pdf"),
                task_id=str(value.get("taskId") or ""),
                message_id=int(value.get("messageId") or 0),
                document_id=int(value.get("documentId") or 0),
                prompt_message_id=int(value.get("promptMessageId") or 0),
                title=str(value.get("title") or ""),
                tags=tuple(str(item) for item in value.get("tags") or ()),
            )
            if record.source_id and record.sha256:
                sources[record.source_id] = record
        hashes = {
            str(key): str(value)
            for key, value in dict(raw.get("hashes") or {}).items()
            if str(key) and str(value) in sources
        }
        if not hashes:
            hashes = {record.sha256: key for key, record in sources.items()}
        pending = {}
        for key, value in dict(raw.get("pending") or {}).items():
            if not isinstance(value, dict):
                continue
            try:
                item = PendingDocument(
                    source_id=str(value.get("sourceId") or key),
                    channel_id=int(value.get("channelId") or self.channel_id),
                    message_id=int(value.get("messageId") or 0),
                    attachment_id=int(value.get("attachmentId") or 0),
                    prompt_message_id=int(value.get("promptMessageId") or 0),
                    author_id=int(value.get("authorId") or 0),
                    sha256=str(value.get("sha256") or ""),
                    filename=str(value.get("filename") or "document.pdf"),
                )
            except (TypeError, ValueError):
                continue
            if item.source_id and item.message_id and item.attachment_id and item.sha256:
                pending[item.source_id] = item
        return DiscordInboxState(sources=sources, hashes=hashes, pending=pending)

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sources": {
                key: {
                    "sourceId": record.source_id,
                    "sha256": record.sha256,
                    "filename": record.filename,
                    "taskId": record.task_id,
                    "messageId": record.message_id,
                    "documentId": record.document_id,
                    "promptMessageId": record.prompt_message_id,
                    "title": record.title,
                    "tags": list(record.tags),
                }
                for key, record in self.state.sources.items()
            },
            "hashes": self.state.hashes,
            "pending": {
                key: {
                    "sourceId": item.source_id,
                    "channelId": item.channel_id,
                    "messageId": item.message_id,
                    "attachmentId": item.attachment_id,
                    "promptMessageId": item.prompt_message_id,
                    "authorId": item.author_id,
                    "sha256": item.sha256,
                    "filename": item.filename,
                }
                for key, item in self.state.pending.items()
            },
        }
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o660)
        temporary.replace(self.state_path)

    def _is_own_message(self, message: discord.Message) -> bool:
        user = getattr(self.bot, "user", None)
        return user is not None and int(getattr(message.author, "id", 0)) == int(getattr(user, "id", 0))

class InboxMenuView(discord.ui.View):
    def __init__(self, inbox: DiscordDocumentInbox, source_id: str) -> None:
        super().__init__(timeout=None)
        self.inbox = inbox
        self.source_id = source_id
        add_metadata = discord.ui.Button(
            label="Manual",
            style=discord.ButtonStyle.primary,
            custom_id="paperless-inbox:manual",
        )
        process = discord.ui.Button(
            label="Process as is",
            style=discord.ButtonStyle.success,
            custom_id="paperless-inbox:process-as-is",
        )
        close = discord.ui.Button(
            label="Close",
            style=discord.ButtonStyle.secondary,
            custom_id="paperless-inbox:close",
        )
        add_metadata.callback = self._add_metadata
        process.callback = self._process_as_is
        close.callback = self._close
        self.add_item(add_metadata)
        self.add_item(process)
        self.add_item(close)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.inbox.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _add_metadata(self, interaction: discord.Interaction) -> None:
        pending = self.inbox.state.pending.get(self.source_id)
        if pending is None:
            await interaction.response.edit_message(
                content="## Documents\nThis item is no longer pending.",
                view=InboxClosedView(),
                allowed_mentions=NO_MENTIONS,
            )
            return
        await interaction.response.send_modal(PendingDocumentMetadataModal(self.inbox, self.source_id, pending))

    async def _process_as_is(self, interaction: discord.Interaction) -> None:
        pending = self.inbox.state.pending.get(self.source_id)
        if pending is None:
            await interaction.response.edit_message(
                content="## Documents\nThis item is no longer pending.",
                view=InboxClosedView(),
                allowed_mentions=NO_MENTIONS,
            )
            return
        await interaction.response.defer()
        try:
            await interaction.edit_original_response(
                content=render_processing_message(pending.filename),
                view=None,
                allowed_mentions=NO_MENTIONS,
            )
            record = await self.inbox.process_pending(self.source_id)
            await interaction.edit_original_response(
                content=render_submitted_message(record),
                view=InboxClosedView(),
                allowed_mentions=NO_MENTIONS,
            )
            self.inbox.track_ocr(record)
        except (DocumentIntakeError, discord.HTTPException) as exc:
            self.inbox.rejected_count += 1
            self.inbox.last_error = str(exc)
            await interaction.followup.send(
                f"Documents import failed: {escape_text(rejection_message(exc))}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )

    async def _close(self, interaction: discord.Interaction) -> None:
        await self.inbox.close_pending(self.source_id)
        await interaction.response.edit_message(
            content="## Documents\nClosed.",
            view=InboxClosedView(),
            allowed_mentions=NO_MENTIONS,
        )


class InboxClosedView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Closed", style=discord.ButtonStyle.secondary, disabled=True))


class OcrReadyView(discord.ui.View):
    def __init__(self, inbox: DiscordDocumentInbox, source_id: str) -> None:
        super().__init__(timeout=None)
        self.inbox = inbox
        self.source_id = source_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.inbox.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, custom_id="paperless-ocr:edit")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        record = self.inbox.state.sources.get(self.source_id)
        if record is None or record.document_id <= 0:
            await interaction.response.send_message("Document is no longer available.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.send_modal(DocumentMetadataModal(self.inbox, self.source_id, record))

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, custom_id="paperless-ocr:done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        record = self.inbox.state.sources.get(self.source_id)
        if record is None or record.document_id <= 0:
            await interaction.response.send_message("Document is no longer available.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.edit_message(
            content=render_ocr_done_message(record),
            view=None,
            allowed_mentions=NO_MENTIONS,
        )


class PendingDocumentMetadataModal(discord.ui.Modal):
    def __init__(self, inbox: DiscordDocumentInbox, source_id: str, pending: PendingDocument) -> None:
        super().__init__(title="Document metadata")
        self.inbox = inbox
        self.source_id = source_id
        inferred_title = Path(pending.filename).stem
        self.title_input = discord.ui.TextInput(
            label="Title",
            default="" if degraded_discord_filename(pending.filename) else inferred_title,
            placeholder="문서 제목",
            max_length=128,
            required=True,
        )
        self.tags_input = discord.ui.TextInput(
            label="Tags",
            placeholder="#tag1 #tag2 #tag3",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=False,
        )
        self.add_item(self.title_input)
        self.add_item(self.tags_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        pending = self.inbox.state.pending.get(self.source_id)
        if pending is None:
            await interaction.response.send_message(
                "This item is no longer pending.",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        title = " ".join(str(self.title_input.value or "").split())
        tags = parse_tag_text(str(self.tags_input.value or ""))
        if not title:
            await interaction.response.send_message("Title is required.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        try:
            await self.inbox._edit_prompt(
                pending,
                render_processing_message(pending.filename),
                view=None,
            )
            record = await self.inbox.process_pending(self.source_id, title=title, tags=tags)
            await self.inbox._edit_prompt(
                pending,
                render_submitted_message(record),
                view=InboxClosedView(),
            )
            self.inbox.track_ocr(record)
        except (DocumentIntakeError, discord.HTTPException) as exc:
            self.inbox.rejected_count += 1
            self.inbox.last_error = str(exc)
            await interaction.followup.send(
                f"Documents import failed: {escape_text(rejection_message(exc))}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )


class DocumentMetadataModal(discord.ui.Modal):
    def __init__(self, inbox: DiscordDocumentInbox, source_id: str, record: InboxRecord) -> None:
        super().__init__(title="Edit document")
        self.inbox = inbox
        self.source_id = source_id
        self.title_input = discord.ui.TextInput(
            label="Title",
            default=record.title or Path(record.filename).stem,
            max_length=128,
            required=True,
        )
        self.tags_input = discord.ui.TextInput(
            label="Tags",
            default=" ".join(f"#{tag}" for tag in record.tags),
            placeholder="#tag1 #tag2 #tag3",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=False,
        )
        self.add_item(self.title_input)
        self.add_item(self.tags_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = " ".join(str(self.title_input.value or "").split())
        tags = parse_tag_text(str(self.tags_input.value or ""))
        if not title:
            await interaction.response.send_message("Title is required.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        try:
            record = await self.inbox.update_record_metadata(self.source_id, title=title, tags=tags)
        except (DocumentIntakeError, discord.HTTPException) as exc:
            self.inbox.last_error = str(exc)
            await interaction.followup.send(
                f"Documents metadata update failed: {escape_text(rejection_message(exc))}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await interaction.edit_original_response(
            content=render_ocr_ready_message(record),
            view=OcrReadyView(self.inbox, self.source_id),
            allowed_mentions=NO_MENTIONS,
        )
