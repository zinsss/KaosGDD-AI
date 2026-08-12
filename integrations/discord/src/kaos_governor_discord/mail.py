from __future__ import annotations

from pathlib import PurePath

from kaos_governor.mail import Attachment, MailMessage

from .markdown import MarkdownField, MarkdownMessage, MarkdownMessageTooLong


def safe_attachment_filename(attachment: Attachment) -> str:
    filename = PurePath(attachment.filename.replace("\\", "/")).name
    cleaned = "".join(character for character in filename if character.isprintable() and character not in "\r\n")
    return cleaned[:180] or "attachment"


def render_mail_summary(mail: MailMessage, max_attachment_bytes: int) -> str:
    attachments = []
    for attachment in mail.attachments[:8]:
        label = safe_attachment_filename(attachment)
        if not attachment.content:
            label += " (empty)"
        elif len(attachment.content) > max_attachment_bytes:
            label += " (over size limit)"
        attachments.append(f"Attachment: {label}")
    if len(mail.attachments) > 8:
        attachments.append(f"{len(mail.attachments) - 8} more attachments")

    preview = "\n".join(mail.preview.splitlines()[:15]).strip() or "(No preview text)"
    for preview_limit in (900, 600, 300, 0):
        quote = preview[:preview_limit].rstrip() if preview_limit else None
        try:
            return MarkdownMessage(
                title="Naver Mail",
                fields=(
                    MarkdownField("Folder", mail.mailbox[:160]),
                    MarkdownField("From", mail.sender[:300]),
                    MarkdownField("Date", mail.received_at[:128]),
                    MarkdownField("Subject", mail.subject[:400]),
                ),
                bullets=tuple(attachments),
                quote=quote,
                footer="Fetched read-only by KaosGovernor",
            ).render()
        except MarkdownMessageTooLong:
            continue
    raise MarkdownMessageTooLong("Naver mail metadata exceeds Discord message limit")
