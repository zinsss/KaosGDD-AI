from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from kaos_governor.mail import MailMessage
from kaos_governor_discord.organizer import (
    DiscordMailOrganizer,
    MailDigestView,
    MailItemActionView,
    render_digest,
    render_digest_item,
)


def digest(count: int) -> dict[str, object]:
    items = {
        f"item-{index}": {
            "subject": f"Unread subject {index}",
            "sender": "sender@example.test",
            "mailboxName": "각종공문",
        }
        for index in range(count)
    }
    return {
        "id": "digest-1",
        "createdAt": "2026-08-12T09:00:00+09:00",
        "totalUnread": count,
        "items": items,
        "order": list(items),
    }


class DiscordOrganizerRenderingTests(unittest.TestCase):
    def test_digest_renders_markdown_without_a_select_menu(self) -> None:
        value = digest(3)
        rendered = render_digest(value)
        self.assertIn("## Naver Mail Organizer", rendered)
        self.assertIn("direct actions", rendered)
        self.assertNotIn("Page", rendered)

    def test_item_message_is_compact_and_escapes_mail_content(self) -> None:
        value = digest(1)
        value["items"]["item-0"]["subject"] = "**unsafe** @everyone"
        rendered = render_digest_item(value["items"]["item-0"])
        self.assertIn("\\*\\*unsafe\\*\\* @\u200beveryone", rendered)
        self.assertLessEqual(len(rendered), 900)


class DiscordOrganizerViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_digest_components_have_stable_custom_ids(self) -> None:
        coordinator = SimpleNamespace(policy=SimpleNamespace())
        header = MailDigestView(coordinator, "digest-1")
        item = MailItemActionView(coordinator, "digest-1", "item-1")
        header_ids = [child.custom_id for child in header.children]
        item_ids = [child.custom_id for child in item.children]
        self.assertEqual(header_ids, ["mail:menu:digest-1", "mail:close:digest-1"])
        self.assertEqual(
            item_ids,
            [
                "mail:item:import:digest-1:item-1",
                "mail:item:read:digest-1:item-1",
                "mail:item:delete:digest-1:item-1",
            ],
        )

    async def test_digest_and_import_use_their_separate_channels(self) -> None:
        service = SimpleNamespace(
            naver_config=SimpleNamespace(max_attachment_bytes=1024),
            attach_message=Mock(),
            attach_item_message=Mock(),
            fetch_item=Mock(
                return_value=MailMessage(
                    mailbox="INBOX",
                    uid=1,
                    sender="sender@example.test",
                    subject="Subject",
                    preview="Preview",
                    attachments=(),
                    received_at="2026-08-12 09:00 KST",
                )
            ),
            import_progress=Mock(return_value={}),
            mark_import_summary=Mock(),
            remove_imported=Mock(),
        )
        coordinator = DiscordMailOrganizer(
            SimpleNamespace(), service, SimpleNamespace(), 100, 200
        )
        organizer_channel = AsyncMock()
        organizer_channel.send.side_effect = [SimpleNamespace(id=501), SimpleNamespace(id=502)]
        archive_channel = AsyncMock()
        archive_channel.send.return_value = SimpleNamespace(id=601)
        coordinator.channel = AsyncMock(return_value=organizer_channel)
        coordinator.archive_channel = AsyncMock(return_value=archive_channel)

        await coordinator.publish_digest(digest(1))
        await coordinator.import_item("digest-1", "item-0")

        self.assertEqual(organizer_channel.send.await_count, 2)
        archive_channel.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
