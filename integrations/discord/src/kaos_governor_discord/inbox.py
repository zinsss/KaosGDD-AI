from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
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


@dataclass
class DiscordInboxState:
    sources: dict[str, InboxRecord] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)


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
        if not message.attachments:
            await message.reply(
                "Upload one or more PDF files to send them to Paperless.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return True

        lines = []
        for attachment in message.attachments:
            try:
                result = await self.submit_attachment(message, attachment)
                if result["duplicate"]:
                    self.duplicate_count += 1
                    lines.append(f"- {escape_text(result['filename'])}: already submitted")
                else:
                    self.accepted_count += 1
                    task = f" `{escape_text(result['taskId'])}`" if result["taskId"] else ""
                    lines.append(f"- {escape_text(result['filename'])}: submitted{task}")
            except (DocumentIntakeError, discord.HTTPException) as exc:
                self.rejected_count += 1
                self.last_error = str(exc)
                lines.append(f"- {escape_text(attachment.filename)}: {escape_text(rejection_message(exc))}")
        await message.reply(
            "\n".join(["## Paperless inbox", *lines])[:1990],
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )
        return True

    async def submit_attachment(self, message: discord.Message, attachment: discord.Attachment) -> dict[str, Any]:
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
        content = await attachment.read(use_cached=True)
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
        result = await asyncio.to_thread(
            self.paperless.submit_pdf,
            safe_filename(attachment.filename),
            content,
            title=Path(attachment.filename).stem,
            source="discord",
        )
        record = InboxRecord(
            source_id=source_id,
            sha256=result.sha256,
            filename=result.filename,
            task_id=result.task_id,
            message_id=int(message.id),
        )
        self.state.sources[source_id] = record
        self.state.hashes[result.sha256] = source_id
        self._save_state()
        self.last_error = ""
        return {
            "duplicate": False,
            "filename": result.filename,
            "taskId": result.task_id,
            "sha256": result.sha256,
        }

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "acceptedCount": self.accepted_count,
            "duplicateCount": self.duplicate_count,
            "rejectedCount": self.rejected_count,
            "trackedSources": len(self.state.sources),
            "trackedHashes": len(self.state.hashes),
            "lastError": self.last_error,
            "paperless": self.paperless.status(),
        }

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
        return DiscordInboxState(sources=sources, hashes=hashes)

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
                }
                for key, record in self.state.sources.items()
            },
            "hashes": self.state.hashes,
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
    }
    return labels.get(str(error), str(error))
