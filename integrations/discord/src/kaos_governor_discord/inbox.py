from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any

import discord
from kaos_governor.documents import DocumentIntakeError, PaperlessDocumentService

from .access import AccessPolicy
from .fax import safe_filename
from .markdown import NO_MENTIONS, escape_text


LOGGER = logging.getLogger(__name__)


@dataclass
class InboxRecord:
    source_id: str
    sha256: str
    filename: str
    task_id: str
    message_id: int
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
        state_path: Path,
        paperless: PaperlessDocumentService,
    ) -> None:
        self.bot = bot
        self.policy = policy
        self.channel_id = channel_id
        self.state_path = state_path
        self.paperless = paperless
        self.state = self._load_state()
        self.accepted_count = 0
        self.duplicate_count = 0
        self.rejected_count = 0
        self.last_error = ""

    async def handle_message(self, message: discord.Message) -> bool:
        if message.channel.id != self.channel_id:
            return False
        if message.author.bot:
            return self._is_own_message(message)
        if not self.policy.allows(message.guild.id if message.guild else None, message.channel.id, message.author.id):
            LOGGER.warning("Rejected inbox message channel=%s user=%s", message.channel.id, message.author.id)
            return False
        if await self._handle_metadata_reply(message):
            return True
        if not message.attachments:
            await message.reply(
                "Upload one PDF file to prepare it for Paperless.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return True
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
                    f"## Paperless inbox\n- {escape_text(result['filename'])}: already submitted",
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
                f"## Paperless inbox\n- {escape_text(attachment.filename)}: {escape_text(rejection_message(exc))}",
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
                "filename": record.filename,
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
        content = await attachment.read(use_cached=True)
        if not content.startswith(b"%PDF-"):
            raise DocumentIntakeError("invalid_pdf_signature")
        digest = hashlib.sha256(content).hexdigest()
        if digest in self.state.hashes:
            source = self.state.hashes[digest]
            record = self.state.sources[source]
            self.state.sources[source_id] = record
            self._save_state()
            return {
                "duplicate": True,
                "filename": record.filename,
                "taskId": record.task_id,
                "sha256": record.sha256,
            }
        pending = PendingDocument(
            source_id=source_id,
            channel_id=int(message.channel.id),
            message_id=int(message.id),
            attachment_id=int(attachment.id),
            prompt_message_id=0,
            author_id=int(message.author.id),
            sha256=digest,
            filename=safe_filename(attachment.filename),
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
        content = await attachment.read(use_cached=True)
        digest = hashlib.sha256(content).hexdigest()
        if digest != pending.sha256:
            raise DocumentIntakeError("paperless_attachment_changed")
        if digest in self.state.hashes:
            record = self.state.sources[self.state.hashes[digest]]
            self.state.sources[source_id] = record
            self.state.pending.pop(source_id, None)
            self._save_state()
            return record
        result = await asyncio.to_thread(
            self.paperless.submit_pdf,
            pending.filename,
            content,
            title=title or Path(pending.filename).stem,
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
            title=title or Path(pending.filename).stem,
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
                await message.edit(
                    content=render_pending_message(pending.filename),
                    view=InboxMenuView(self, source_id),
                    allowed_mentions=NO_MENTIONS,
                )
                restored += 1
            except discord.HTTPException:
                LOGGER.info("Could not restore Paperless inbox prompt %s", pending.prompt_message_id)
        return restored

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "acceptedCount": self.accepted_count,
            "duplicateCount": self.duplicate_count,
            "rejectedCount": self.rejected_count,
            "pendingCount": len(self.state.pending),
            "trackedSources": len(self.state.sources),
            "trackedHashes": len(self.state.hashes),
            "lastError": self.last_error,
            "paperless": self.paperless.status(),
        }

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
            record = await self.process_pending(pending.source_id, title=title, tags=tags)
            await self._edit_prompt(
                pending,
                render_submitted_message(record),
                view=InboxClosedView(),
            )
        except (DocumentIntakeError, discord.HTTPException) as exc:
            self.rejected_count += 1
            self.last_error = str(exc)
            await message.reply(
                f"Paperless import failed: {escape_text(rejection_message(exc))}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
        return True

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


def rejection_message(error: Exception) -> str:
    labels = {
        "paperless_not_configured": "Paperless is not configured.",
        "pdf_attachment_required": "Only PDF attachments are accepted.",
        "pdf_size_invalid": "The PDF is empty or exceeds the configured size limit.",
        "invalid_pdf_signature": "The uploaded file is not a valid PDF.",
        "paperless_request_failed": "Paperless is not reachable.",
        "paperless_pending_missing": "This inbox item is no longer pending.",
        "paperless_source_unavailable": "The original upload is not available.",
        "paperless_attachment_missing": "The original PDF attachment is missing.",
        "paperless_attachment_changed": "The original PDF attachment changed.",
    }
    return labels.get(str(error), str(error))


class InboxMenuView(discord.ui.View):
    def __init__(self, inbox: DiscordDocumentInbox, source_id: str) -> None:
        super().__init__(timeout=None)
        self.inbox = inbox
        self.source_id = source_id
        add_metadata = discord.ui.Button(
            label="Add Metadata",
            style=discord.ButtonStyle.primary,
            custom_id="paperless-inbox:add-metadata",
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
                content="## Paperless inbox\nThis item is no longer pending.",
                view=InboxClosedView(),
                allowed_mentions=NO_MENTIONS,
            )
            return
        await interaction.response.edit_message(
            content=render_metadata_message(pending.filename),
            view=self,
            allowed_mentions=NO_MENTIONS,
        )

    async def _process_as_is(self, interaction: discord.Interaction) -> None:
        pending = self.inbox.state.pending.get(self.source_id)
        if pending is None:
            await interaction.response.edit_message(
                content="## Paperless inbox\nThis item is no longer pending.",
                view=InboxClosedView(),
                allowed_mentions=NO_MENTIONS,
            )
            return
        await interaction.response.defer()
        try:
            record = await self.inbox.process_pending(self.source_id)
            await interaction.edit_original_response(
                content=render_submitted_message(record),
                view=InboxClosedView(),
                allowed_mentions=NO_MENTIONS,
            )
        except (DocumentIntakeError, discord.HTTPException) as exc:
            self.inbox.rejected_count += 1
            self.inbox.last_error = str(exc)
            await interaction.followup.send(
                f"Paperless import failed: {escape_text(rejection_message(exc))}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )

    async def _close(self, interaction: discord.Interaction) -> None:
        await self.inbox.close_pending(self.source_id)
        await interaction.response.edit_message(
            content="## Paperless inbox\nClosed.",
            view=InboxClosedView(),
            allowed_mentions=NO_MENTIONS,
        )


class InboxClosedView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Closed", style=discord.ButtonStyle.secondary, disabled=True))


def render_pending_message(filename: str) -> str:
    return "\n".join(
        (
            "## Paperless inbox",
            f"### {escape_text(filename)}",
            "Choose how to process this document.",
        )
    )[:1990]


def render_metadata_message(filename: str) -> str:
    return "\n".join(
        (
            "## Paperless inbox",
            f"### {escape_text(filename)}",
            "Reply to this message with:",
            "```md",
            "### {title of document}",
            "#tag1 #tag2 #tag3",
            "```",
        )
    )[:1990]


def render_submitted_message(record: InboxRecord) -> str:
    task = f" `{escape_text(record.task_id)}`" if record.task_id else ""
    lines = ["## Paperless inbox", f"- {escape_text(record.filename)}: submitted{task}"]
    if record.title:
        lines.append(f"- title: {escape_text(record.title)}")
    if record.tags:
        lines.append("- tags: " + " ".join(f"#{escape_text(tag)}" for tag in record.tags))
    return "\n".join(lines)[:1990]


def metadata_instruction() -> str:
    return "\n".join(
        (
            "Use this format:",
            "```md",
            "### {title of document}",
            "#tag1 #tag2 #tag3",
            "```",
        )
    )


def parse_metadata_reply(content: str) -> tuple[str, tuple[str, ...]] | None:
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    if not lines or not lines[0].startswith("### "):
        return None
    title = lines[0][4:].strip()
    if not title:
        return None
    tags: list[str] = []
    seen: set[str] = set()
    for tag in re.findall(r"#([^\s#]+)", "\n".join(lines[1:])):
        cleaned = tag.strip(".,;:!?) ]}").strip("([{")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            tags.append(cleaned)
    return title, tuple(tags)
