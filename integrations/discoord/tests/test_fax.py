import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from kaos_governor.fax import FaxAction
from kaosdiscoord.fax import (
    DiscordFaxTransport,
    faxable_attachment_name,
    image_to_pdf,
    rejection_message,
    safe_filename,
    watch_fax_message,
)


class DiscordFaxTests(unittest.TestCase):
    def test_korean_archive_filename_is_preserved(self) -> None:
        self.assertEqual(safe_filename("../초2_문제집.pdf"), "초2_문제집.pdf")

    def test_image_attachment_name_preserves_stem_as_pdf(self) -> None:
        self.assertEqual(faxable_attachment_name("../처방전 사진.jpeg"), "처방전 사진.pdf")

    def test_image_attachment_converts_to_pdf(self) -> None:
        image = Image.new("RGBA", (40, 30), (120, 40, 80, 255))
        source = BytesIO()
        image.save(source, format="PNG")

        pdf = image_to_pdf(source.getvalue())

        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_rejection_explains_reply_contract(self) -> None:
        value = rejection_message(ValueError("reply_to_pdf_required"))
        self.assertIn("Reply directly to one PDF or image", value)

    def test_watch_copy_only_reports_final_fax_states(self) -> None:
        self.assertEqual(watch_fax_message(FaxAction("incoming:archive:1", "archive")), "Fax received.")
        self.assertEqual(watch_fax_message(FaxAction("outgoing:discord:1:sent", "notification")), "Fax sent.")
        self.assertEqual(watch_fax_message(FaxAction("outgoing:discord:1:failed", "notification")), "Fax send failed.")
        self.assertEqual(watch_fax_message(FaxAction("outgoing:discord:1:queued", "notification")), "")
        self.assertEqual(watch_fax_message(FaxAction("outgoing:discord:1:sending", "notification")), "")


class DiscordFaxTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_notification_is_mirrored_after_discord(self) -> None:
        service = SimpleNamespace(
            scan_actions=mock.Mock(),
            acknowledge=mock.Mock(),
            record_error=mock.Mock(),
        )
        notifier = SimpleNamespace(notify=mock.Mock())
        transport = DiscordFaxTransport(
            SimpleNamespace(),  # type: ignore[arg-type]
            service,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            archive_channel_id=300,
            notification_channel_id=301,
            text_notifications=notifier,  # type: ignore[arg-type]
        )
        notification_channel = SimpleNamespace(send=mock.AsyncMock())
        transport._channel = mock.AsyncMock(return_value=notification_channel)  # type: ignore[method-assign]
        action = FaxAction(
            "outgoing:discord:event-1:sent",
            "notification",
            content="Fax successfully sent.",
        )

        await transport._notification(action)

        notification_channel.send.assert_awaited_once()
        notifier.notify.assert_called_once()
        mirrored = notifier.notify.call_args.args[0]
        self.assertEqual(mirrored.category, "fax")
        self.assertEqual(mirrored.key, "fax:outgoing:discord:event-1:sent")
        self.assertEqual(mirrored.title, "")
        self.assertEqual(mirrored.message, "Fax sent.")
        self.assertEqual(mirrored.priority, 0)

    async def test_failed_fax_is_high_priority(self) -> None:
        notifier = SimpleNamespace(notify=mock.Mock())
        transport = DiscordFaxTransport(
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            archive_channel_id=300,
            notification_channel_id=301,
            text_notifications=notifier,  # type: ignore[arg-type]
        )
        transport._channel = mock.AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(send=mock.AsyncMock())
        )

        await transport._notification(
            FaxAction("outgoing:discord:event-1:failed", "notification", "Fax failed.")
        )

        self.assertEqual(notifier.notify.call_args.args[0].priority, 1)

    async def test_transient_fax_progress_is_not_sent_to_watch(self) -> None:
        notifier = SimpleNamespace(notify=mock.Mock())
        transport = DiscordFaxTransport(
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            archive_channel_id=300,
            notification_channel_id=301,
            text_notifications=notifier,  # type: ignore[arg-type]
        )
        notification_channel = SimpleNamespace(send=mock.AsyncMock())
        transport._channel = mock.AsyncMock(return_value=notification_channel)  # type: ignore[method-assign]

        await transport._notification(FaxAction("outgoing:discord:event-1:queued", "notification", "Queued."))

        notification_channel.send.assert_awaited_once()
        notifier.notify.assert_not_called()

    async def test_received_fax_is_stored_and_only_text_is_sent_to_notifications(self) -> None:
        service = SimpleNamespace(store_incoming_document=mock.Mock())
        notifier = SimpleNamespace(notify=mock.Mock())
        transport = DiscordFaxTransport(
            SimpleNamespace(),  # type: ignore[arg-type]
            service,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            archive_channel_id=300,
            notification_channel_id=301,
            text_notifications=notifier,  # type: ignore[arg-type]
        )
        notification_channel = SimpleNamespace(send=mock.AsyncMock())
        transport._channel = mock.AsyncMock(return_value=notification_channel)  # type: ignore[method-assign]
        action = FaxAction(
            "incoming:archive:event-1",
            "archive",
            content="Fax received.\n: from 07079664986",
            filename="incoming.pdf",
            content_bytes=b"%PDF-received",
        )

        await transport._archive(action)

        service.store_incoming_document.assert_called_once_with(action, b"%PDF-received")
        transport._channel.assert_awaited_once_with(301)
        notification_channel.send.assert_awaited_once()
        self.assertNotIn("file", notification_channel.send.await_args.kwargs)
        mirrored = notifier.notify.call_args.args[0]
        self.assertEqual(mirrored.category, "fax")
        self.assertEqual(mirrored.message, "Fax received.")
        self.assertEqual(mirrored.priority, 0)
        self.assertFalse(hasattr(mirrored, "content_bytes"))


if __name__ == "__main__":
    unittest.main()
