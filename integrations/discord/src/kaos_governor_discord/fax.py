from __future__ import annotations

import asyncio
from contextlib import suppress
import io
import logging
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata

import discord
from kaos_governor.fax import FaxAction, FaxError, FaxService, request_from_pdf

from .access import AccessPolicy
from .markdown import NO_MENTIONS


LOGGER = logging.getLogger(__name__)
FAX_COMMAND = re.compile(r"^\s*fax\s*:\s*([+0-9][0-9\s().-]*)\s*$", re.IGNORECASE)


def safe_filename(value: str) -> str:
    filename = unicodedata.normalize("NFC", Path(value or "fax.pdf").name)
    filename = re.sub(r'[\x00-\x1f\x7f"\\/]+', "-", filename).strip(" .-")
    return filename or "fax.pdf"


def rejection_message(error: Exception) -> str:
    labels = {
        "invalid_domestic_fax_number": "The fax number is invalid.",
        "pdf_attachment_required": "Only one PDF document can be faxed.",
        "pdf_size_invalid": "The PDF is empty or exceeds the configured size limit.",
        "invalid_pdf_signature": "The uploaded document is not a valid PDF.",
        "reply_to_pdf_required": "Reply directly to one PDF with fax:<number>.",
        "caption_must_be_fax_colon_number": "Use fax:<number> with the PDF, or reply to it with fax:<number>.",
    }
    return f"Fax request rejected.\n{labels.get(str(error), str(error))}"


class DiscordFaxTransport:
    def __init__(
        self,
        client: discord.Client,
        service: FaxService,
        policy: AccessPolicy,
        archive_channel_id: int,
        notification_channel_id: int,
    ) -> None:
        self.client = client
        self.service = service
        self.policy = policy
        self.archive_channel_id = archive_channel_id
        self.notification_channel_id = notification_channel_id
        self._cycle_lock = asyncio.Lock()

    async def _channel(self, channel_id: int) -> discord.abc.Messageable:
        channel = self.client.get_channel(channel_id) or await self.client.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("fax_channel_not_messageable")
        return channel

    async def _notification(self, action: FaxAction) -> None:
        channel = await self._channel(self.notification_channel_id)
        await channel.send(action.content, allowed_mentions=NO_MENTIONS)

    @staticmethod
    def _convert_tiff(source: Path, destination: Path) -> None:
        result = subprocess.run(
            ["tiff2pdf", "-o", str(destination), str(source)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not destination.is_file() or destination.stat().st_size <= 0:
            reason = (result.stderr or result.stdout or "tiff2pdf_failed").strip()
            raise RuntimeError(reason)

    async def _archive(self, action: FaxAction) -> None:
        if action.path is None and not action.content_bytes:
            raise RuntimeError("fax_archive_path_missing")
        channel = await self._channel(self.archive_channel_id)
        source = action.path
        temporary = None
        try:
            if action.content_bytes:
                kwargs = {
                    "file": discord.File(io.BytesIO(action.content_bytes), filename=safe_filename(action.filename)),
                    "allowed_mentions": NO_MENTIONS,
                }
                if action.content:
                    kwargs["content"] = action.content
                await channel.send(**kwargs)
                return
            if source is not None and source.suffix.lower() in {".tif", ".tiff"}:
                temporary = tempfile.TemporaryDirectory(prefix="kaos-discord-fax-")
                source = Path(temporary.name) / safe_filename(action.filename)
                await asyncio.to_thread(self._convert_tiff, action.path, source)
            kwargs = {
                "file": discord.File(source, filename=safe_filename(action.filename)),
                "allowed_mentions": NO_MENTIONS,
            }
            if action.content:
                kwargs["content"] = action.content
            await channel.send(**kwargs)
        finally:
            if temporary is not None:
                temporary.cleanup()

    async def _cleanup(self, action: FaxAction) -> None:
        if not action.channel_id:
            return
        channel = await self._channel(action.channel_id)
        if not hasattr(channel, "fetch_message"):
            raise RuntimeError("fax_cleanup_channel_not_fetchable")
        for message_id in action.message_ids:
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except discord.NotFound:
                pass

    async def cycle(self) -> int:
        async with self._cycle_lock:
            actions = await asyncio.to_thread(self.service.scan_actions)
            completed = 0
            for action in actions:
                try:
                    if action.kind == "notification":
                        await self._notification(action)
                    elif action.kind == "archive":
                        await self._archive(action)
                    elif action.kind == "cleanup":
                        await self._cleanup(action)
                    else:
                        raise RuntimeError(f"unknown_fax_action:{action.kind}")
                    await asyncio.to_thread(self.service.acknowledge, action)
                    completed += 1
                except (OSError, RuntimeError, discord.HTTPException) as exc:
                    self.service.record_error(exc)
                    LOGGER.exception("Fax action failed: %s", action.key)
                    break
            return completed

    async def submit_attachment(
        self,
        attachment: discord.Attachment,
        destination: str,
        *,
        sender: str,
        source_id: str,
        metadata: dict[str, object],
    ) -> tuple[dict, bool]:
        if not attachment.filename.lower().endswith(".pdf"):
            raise FaxError("pdf_attachment_required")
        if attachment.size <= 0 or attachment.size > self.service.config.max_pdf_bytes:
            raise FaxError("pdf_size_invalid")
        pdf = await attachment.read(use_cached=True)
        request = request_from_pdf(
            destination=destination,
            sender=sender,
            source_id=source_id,
            filename=attachment.filename,
            pdf=pdf,
            max_bytes=self.service.config.max_pdf_bytes,
        )
        result = await asyncio.to_thread(self.service.submit, request, metadata)
        await self.cycle()
        return result

    async def _referenced_message(self, message: discord.Message) -> discord.Message | None:
        if message.reference is None or message.reference.message_id is None:
            return None
        if isinstance(message.reference.resolved, discord.Message):
            return message.reference.resolved
        with suppress(discord.NotFound):
            return await message.channel.fetch_message(message.reference.message_id)
        return None

    async def handle_message(self, message: discord.Message) -> bool:
        if message.author.bot or message.channel.id != self.archive_channel_id:
            return False
        if not self.policy.allows(message.guild.id if message.guild else None, message.channel.id, message.author.id):
            LOGGER.warning("Rejected fax message channel=%s user=%s", message.channel.id, message.author.id)
            return False
        command_message = message
        document_message = message
        attachment = message.attachments[0] if len(message.attachments) == 1 else None
        destination = ""
        if attachment is not None:
            if not attachment.filename.lower().endswith(".pdf"):
                return False
            if not message.content.strip():
                prompt = await message.reply(
                    "Reply directly to this PDF with fax:<number>.",
                    mention_author=False,
                    allowed_mentions=NO_MENTIONS,
                )
                await asyncio.to_thread(self.service.remember_prompt, message.id, prompt.id)
                return True
            match = FAX_COMMAND.fullmatch(message.content)
            if not match:
                await message.reply(rejection_message(FaxError("caption_must_be_fax_colon_number")), mention_author=False)
                return True
            destination = match.group(1)
        elif message.content.strip().lower().startswith("fax"):
            match = FAX_COMMAND.fullmatch(message.content)
            document_message = await self._referenced_message(message)
            if match is None or document_message is None or len(document_message.attachments) != 1:
                await message.reply(rejection_message(FaxError("reply_to_pdf_required")), mention_author=False)
                return True
            attachment = document_message.attachments[0]
            destination = match.group(1)
        else:
            return False
        try:
            _, created = await self.submit_attachment(
                attachment,
                destination,
                sender=f"discord:{message.author.id}",
                source_id=f"discord:{message.guild.id}:{message.channel.id}:{document_message.id}:{attachment.id}",
                metadata={
                    "guildId": str(message.guild.id),
                    "channelId": message.channel.id,
                    "messageId": document_message.id,
                    "commandMessageId": command_message.id,
                    "userId": str(message.author.id),
                    "attachmentId": str(attachment.id),
                },
            )
            if not created:
                await message.reply("This fax request is already queued.", mention_author=False)
        except (FaxError, discord.HTTPException) as exc:
            await message.reply(rejection_message(exc), mention_author=False, allowed_mentions=NO_MENTIONS)
        return True
