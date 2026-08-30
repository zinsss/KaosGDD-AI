from __future__ import annotations

from pathlib import PurePath
import re

import discord
from kaos_governor.mail import Attachment, MailMessage

from .markdown import DISCORD_MESSAGE_LIMIT, MarkdownMessageTooLong


def safe_attachment_filename(attachment: Attachment) -> str:
    filename = PurePath(attachment.filename.replace("\\", "/")).name
    cleaned = "".join(character for character in filename if character.isprintable() and character not in "\r\n")
    return cleaned[:180] or "attachment"


def _escaped(value: object) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))


def _display_sender(sender: str) -> str:
    return re.sub(r"\s*<([^<>\r\n]+)>", r" \1", sender).strip()


def _attachment_lines(mail: MailMessage, max_attachment_bytes: int, limit: int) -> list[str]:
    attachments: list[str] = []
    for attachment in mail.attachments[:limit]:
        label = safe_attachment_filename(attachment)
        if not attachment.content:
            label += " (empty)"
        elif len(attachment.content) > max_attachment_bytes:
            label += " (over size limit)"
        attachments.append(f"- {_escaped(label)}")
    if len(mail.attachments) > limit:
        attachments.append(f"- {_escaped(f'{len(mail.attachments) - limit} more attachments')}")
    return attachments


def _render_mail_summary_candidate(
    mail: MailMessage,
    max_attachment_bytes: int,
    preview_limit: int,
    attachment_limit: int,
) -> str:
    header = "\n".join(
        (
            "### Naver Mail",
            f"**Folder** {_escaped(mail.mailbox[:160])}",
            f"**From** {_escaped(_display_sender(mail.sender)[:300])}",
            f"**Date** {_escaped(mail.received_at[:128])}",
        )
    )
    sections = [header, f"### {_escaped(mail.subject[:400])}"]
    attachments = _attachment_lines(mail, max_attachment_bytes, attachment_limit)
    if attachments:
        sections.append("***Attachment:***\n" + "\n".join(attachments))
    preview = "\n".join(mail.preview.splitlines()[:15]).strip() or "(No preview text)"
    if preview_limit:
        escaped_preview = _escaped(preview[:preview_limit].rstrip())
        sections.append(
            "\n".join(f"> {line}" if line else ">" for line in escaped_preview.splitlines())
        )
    return "\n\n".join(sections)


def render_mail_summary(mail: MailMessage, max_attachment_bytes: int) -> str:
    for preview_limit in (900, 600, 300, 0):
        content = _render_mail_summary_candidate(mail, max_attachment_bytes, preview_limit, 8)
        if len(content) <= DISCORD_MESSAGE_LIMIT:
            return content
    for attachment_limit in (4, 2, 0):
        content = _render_mail_summary_candidate(mail, max_attachment_bytes, 0, attachment_limit)
        if len(content) <= DISCORD_MESSAGE_LIMIT:
            return content
    raise MarkdownMessageTooLong("Naver mail metadata exceeds Discord message limit")
