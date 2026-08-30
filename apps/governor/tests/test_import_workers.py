from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from kaos_governor.fax import FaxAction
from kaos_governor.import_workers import (
    FaxLifecycleWorker,
    NaverMailLifecycleWorker,
    fax_text_notification,
    mail_text_notification,
)
from kaos_governor.mail import Attachment, MailMessage


class FaxLifecycleWorkerTests(unittest.TestCase):
    def test_processes_without_discord_and_only_queues_final_alerts(self) -> None:
        actions = [
            FaxAction(
                "incoming:archive:event-1",
                "archive",
                filename="received.pdf",
                content_bytes=b"%PDF-received",
            ),
            FaxAction("outgoing:discord:job-1:queued", "notification", "Queued."),
            FaxAction("outgoing:discord:job-1:sending", "notification", "Sending."),
            FaxAction("outgoing:discord:job-1:sent", "notification", "Sent."),
            FaxAction("outgoing:discord:job-2:failed", "notification", "Failed."),
        ]
        service = SimpleNamespace(
            scan_actions=mock.Mock(return_value=actions),
            store_incoming_document=mock.Mock(),
            acknowledge=mock.Mock(),
            record_error=mock.Mock(),
        )
        notifications = SimpleNamespace(enqueue=mock.Mock(return_value=True))
        lifecycle = FaxLifecycleWorker(service, notifications)  # type: ignore[arg-type]

        result = lifecycle.run_once()

        self.assertEqual(result.processed, 5)
        self.assertEqual(result.notification_count, 3)
        service.store_incoming_document.assert_called_once_with(actions[0], b"%PDF-received")
        self.assertEqual([call.args[0] for call in service.acknowledge.call_args_list], actions)
        queued = [call.args[0] for call in notifications.enqueue.call_args_list]
        self.assertEqual(
            [(item.message, item.priority) for item in queued],
            [("Fax received.", 0), ("Fax sent.", 0), ("Fax send failed.", 1)],
        )
        service.record_error.assert_not_called()

    def test_incoming_tiff_uses_injected_converter(self) -> None:
        action = FaxAction("incoming:archive:event-2", "archive", path=Path("incoming.tif"))
        service = SimpleNamespace(
            scan_actions=mock.Mock(return_value=[action]),
            store_incoming_document=mock.Mock(),
            acknowledge=mock.Mock(),
            record_error=mock.Mock(),
        )
        notifications = SimpleNamespace(enqueue=mock.Mock(return_value=False))
        converter = mock.Mock(return_value=b"%PDF-converted")
        lifecycle = FaxLifecycleWorker(  # type: ignore[arg-type]
            service,
            notifications,
            tiff_converter=converter,
        )
        with mock.patch.object(Path, "is_file", return_value=True):
            lifecycle.run_once()

        converter.assert_called_once_with(Path("incoming.tif"))
        service.store_incoming_document.assert_called_once_with(action, b"%PDF-converted")

    def test_alert_policy_omits_transient_states(self) -> None:
        self.assertIsNone(fax_text_notification(FaxAction("job:queued", "notification")))
        failed = fax_text_notification(FaxAction("job:failed", "notification"))
        self.assertIsNotNone(failed)
        self.assertEqual(failed.priority, 1)  # type: ignore[union-attr]


class NaverMailLifecycleWorkerTests(unittest.TestCase):
    @staticmethod
    def message() -> MailMessage:
        return MailMessage(
            mailbox="세무사",
            uid=42,
            sender="sender@example.test",
            subject="Notice",
            preview="Body",
            attachments=(Attachment("notice.pdf", "application/pdf", b"%PDF"),),
            received_at="2026-08-30 17:00 KST",
        )

    def test_keeps_mail_in_imap_and_queues_one_simple_alert(self) -> None:
        mail = self.message()

        def scan(summary_sender, attachment_sender):
            marker = summary_sender(mail)
            attachment_sender(mail.attachments[0])
            self.assertEqual(marker, {"messageId": "imap:세무사:42"})
            return 1

        poller = SimpleNamespace(scan=mock.Mock(side_effect=scan))
        notifications = SimpleNamespace(enqueue=mock.Mock(return_value=True))
        lifecycle = NaverMailLifecycleWorker(poller, notifications)  # type: ignore[arg-type]

        result = lifecycle.run_once()

        self.assertEqual(result.processed, 1)
        self.assertEqual(result.notification_count, 1)
        notification = notifications.enqueue.call_args.args[0]
        self.assertEqual(notification.message, "Mail received.")
        self.assertEqual(notification.priority, 0)
        self.assertEqual(notification.key, mail_text_notification(mail).key)


if __name__ == "__main__":
    unittest.main()
