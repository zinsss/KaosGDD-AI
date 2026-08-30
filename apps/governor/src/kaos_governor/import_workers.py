from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import tempfile
from typing import Callable

from .fax import FaxAction, FaxError, FaxService
from .mail import Attachment, MailMessage, NaverMailPoller
from .notifications import TextNotification, TextNotificationService


def fax_text_notification(action: FaxAction) -> TextNotification | None:
    if action.key.startswith("incoming:"):
        message = "Fax received."
        priority = 0
    elif action.key.endswith(":failed"):
        message = "Fax send failed."
        priority = 1
    elif action.key.endswith(":sent"):
        message = "Fax sent."
        priority = 0
    else:
        return None
    return TextNotification(
        key=f"fax:{action.key}",
        category="fax",
        title="",
        message=message,
        priority=priority,
    )


def mail_text_notification(mail: MailMessage) -> TextNotification:
    identity = "\0".join(
        (mail.mailbox, str(mail.uid), mail.received_at, mail.sender, mail.subject)
    )
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return TextNotification(
        key=f"mail:message:{key}",
        category="mail",
        title="",
        message="Mail received.",
        priority=0,
    )


def _tiff_to_pdf(source: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="kaos-governor-fax-") as temporary:
        destination = Path(temporary) / "incoming.pdf"
        result = subprocess.run(
            ["tiff2pdf", "-o", str(destination), str(source)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not destination.is_file() or destination.stat().st_size <= 0:
            reason = (result.stderr or result.stdout or "tiff2pdf_failed").strip()
            raise FaxError(reason)
        return destination.read_bytes()


@dataclass(frozen=True)
class ImportCycleResult:
    processed: int = 0
    notification_count: int = 0


class FaxLifecycleWorker:
    """Processes fax-domain actions without a Discord transport."""

    def __init__(
        self,
        service: FaxService,
        notifications: TextNotificationService,
        *,
        tiff_converter: Callable[[Path], bytes] | None = None,
    ) -> None:
        self.service = service
        self.notifications = notifications
        self._tiff_converter = tiff_converter or _tiff_to_pdf

    def run_once(self) -> ImportCycleResult:
        completed = 0
        queued = 0
        try:
            actions = self.service.scan_actions()
            for action in actions:
                if action.kind == "archive" and action.key.startswith("incoming:archive:"):
                    self.service.store_incoming_document(action, self._incoming_pdf(action))
                elif action.kind not in {"archive", "notification"}:
                    raise FaxError(f"unknown_fax_action:{action.kind}")

                notification = fax_text_notification(action)
                if notification is not None and self.notifications.enqueue(notification):
                    queued += 1
                # Outgoing documents already remain under the fax queue/archive.
                # Discord source cleanup is exposed separately to KaosDiscoord.
                self.service.acknowledge(action)
                completed += 1
        except Exception as exc:
            self.service.record_error(exc)
            raise
        return ImportCycleResult(completed, queued)

    def _incoming_pdf(self, action: FaxAction) -> bytes:
        if action.content_bytes:
            return action.content_bytes
        if action.path is None or not action.path.is_file():
            raise FaxError("fax_archive_path_missing")
        if action.path.suffix.lower() in {".tif", ".tiff"}:
            return self._tiff_converter(action.path)
        return action.path.read_bytes()


class NaverMailLifecycleWorker:
    """Advances the IMAP checkpoint and emits only a minimal text alert."""

    def __init__(
        self,
        poller: NaverMailPoller,
        notifications: TextNotificationService,
    ) -> None:
        self.poller = poller
        self.notifications = notifications
        self.notification_count = 0

    def run_once(self) -> ImportCycleResult:
        self.notification_count = 0
        archived = self.poller.scan(self._record_mail, self._retain_attachment)
        return ImportCycleResult(archived, self.notification_count)

    def _record_mail(self, mail: MailMessage) -> dict[str, object]:
        if self.notifications.enqueue(mail_text_notification(mail)):
            self.notification_count += 1
        # The authoritative message and attachments stay in Naver IMAP. This
        # durable marker lets the existing retry checkpoint advance without a
        # Discord message ID.
        return {"messageId": f"imap:{mail.mailbox}:{mail.uid}"}

    @staticmethod
    def _retain_attachment(_attachment: Attachment) -> None:
        # Fetching the parent message from Naver retains the attachment there;
        # no second Discord or local attachment archive is created.
        return None
