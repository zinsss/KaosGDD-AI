import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from kaos_governor.fax import FaxAction
from kaos_governor_discord.fax import (
    DiscordFaxTransport,
    faxable_attachment_name,
    image_to_pdf,
    rejection_message,
    safe_filename,
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


class DiscordFaxTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_watch_notification_uses_pushover_without_discord(self) -> None:
        service = SimpleNamespace(
            scan_actions=mock.Mock(),
            acknowledge=mock.Mock(),
            record_error=mock.Mock(),
        )
        pushover = SimpleNamespace(send=mock.Mock())
        transport = DiscordFaxTransport(
            SimpleNamespace(),  # type: ignore[arg-type]
            service,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            archive_channel_id=300,
            notification_channel_id=301,
            pushover_client=pushover,  # type: ignore[arg-type]
        )
        action = FaxAction(
            "incoming:pushover:event-1",
            "watch_notification",
            content="Fax received.\n: from 07079664986",
        )

        await transport._watch_notification(action)

        pushover.send.assert_called_once_with(action)

    async def test_received_fax_is_stored_and_only_text_is_sent_to_notifications(self) -> None:
        service = SimpleNamespace(store_incoming_document=mock.Mock())
        transport = DiscordFaxTransport(
            SimpleNamespace(),  # type: ignore[arg-type]
            service,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            archive_channel_id=300,
            notification_channel_id=301,
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


if __name__ == "__main__":
    unittest.main()
