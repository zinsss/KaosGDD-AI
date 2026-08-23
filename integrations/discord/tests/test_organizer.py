from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from kaos_governor.mail import MailMessage
from kaos_governor_discord.organizer import (
    DiscordMailOrganizer,
    MailBulkView,
    MailDeleteAllConfirmationView,
    MailDigestView,
    MailItemSelect,
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
    def test_digest_renders_compact_numbered_list(self) -> None:
        value = digest(3)
        rendered = render_digest(value)
        self.assertIn("## Naver Mail Organizer", rendered)
        self.assertIn("1. Unread subject 0", rendered)
        self.assertIn("Select one message", rendered)
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
        header = MailDigestView(coordinator, "digest-1", digest(1))
        item = MailItemActionView(coordinator, "digest-1", "item-1")
        header_ids = [child.custom_id for child in header.children]
        item_ids = [child.custom_id for child in item.children]
        self.assertEqual(header_ids, ["mail:select:digest-1", "mail:menu:digest-1", "mail:close:digest-1"])
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
            active_digests=Mock(return_value=[]),
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
        organizer_channel.send.return_value = SimpleNamespace(id=501)
        archive_channel = AsyncMock()
        archive_channel.send.return_value = SimpleNamespace(id=601)
        coordinator.channel = AsyncMock(return_value=organizer_channel)
        coordinator.archive_channel = AsyncMock(return_value=archive_channel)

        await coordinator.publish_digest(digest(1))
        await coordinator.import_item("digest-1", "item-0")

        organizer_channel.send.assert_awaited_once()
        archive_channel.send.assert_awaited_once()

    async def test_publish_digest_deletes_previous_day_snapshot_only(self) -> None:
        old_digest = digest(1)
        old_digest["id"] = "old-digest"
        old_digest["createdAt"] = "2026-08-21T09:00:00+09:00"
        old_digest["channelId"] = 100
        old_digest["messageId"] = 401
        old_digest["items"]["item-0"]["organizerMessageId"] = 402
        same_day_digest = digest(1)
        same_day_digest["id"] = "same-day-digest"
        same_day_digest["createdAt"] = "2026-08-22T08:00:00+09:00"
        same_day_digest["channelId"] = 100
        same_day_digest["messageId"] = 403
        new_digest = digest(1)
        new_digest["id"] = "new-digest"
        new_digest["createdAt"] = "2026-08-22T09:00:00+09:00"
        service = SimpleNamespace(
            active_digests=Mock(return_value=[old_digest, same_day_digest]),
            close_digest=Mock(return_value=old_digest),
            attach_message=Mock(),
            attach_item_message=Mock(),
        )
        deleted_messages = []

        def message(message_id: int):
            item = AsyncMock()
            item.id = message_id

            async def delete() -> None:
                deleted_messages.append(message_id)

            item.delete.side_effect = delete
            return item

        organizer_channel = AsyncMock()
        organizer_channel.fetch_message.side_effect = lambda message_id: message(message_id)
        organizer_channel.send.return_value = SimpleNamespace(id=501)
        bot = SimpleNamespace(
            get_channel=Mock(return_value=organizer_channel),
            fetch_channel=AsyncMock(return_value=organizer_channel),
        )
        coordinator = DiscordMailOrganizer(bot, service, SimpleNamespace(), 100, 200)
        coordinator.channel = AsyncMock(return_value=organizer_channel)

        await coordinator.publish_digest(new_digest)

        service.close_digest.assert_called_once_with("old-digest")
        self.assertEqual(deleted_messages, [402, 401])
        organizer_channel.send.assert_awaited_once()
        service.attach_message.assert_called_once_with("new-digest", 100, 501)

    async def test_mail_select_opens_item_action_panel(self) -> None:
        value = digest(1)
        service = SimpleNamespace(digest=Mock(return_value=value))
        coordinator = SimpleNamespace(
            policy=SimpleNamespace(allows=Mock(return_value=True)),
            organizer=service,
        )
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            user=SimpleNamespace(id=3),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        select = MailItemSelect(coordinator, "digest-1", value)
        select._values = ["item-0"]

        await select.callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        args = interaction.response.send_message.await_args.args
        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertIn("Unread subject 0", args[0])
        self.assertTrue(kwargs["ephemeral"])

    async def test_bulk_mark_read_acknowledges_as_thinking_before_work(self) -> None:
        organizer = SimpleNamespace(
            digest=Mock(return_value=digest(1)),
            mark_read_all=Mock(),
        )
        coordinator = SimpleNamespace(
            policy=SimpleNamespace(allows=Mock(return_value=True)),
            organizer=organizer,
            delete_item_messages=AsyncMock(),
            refresh_digest=AsyncMock(),
        )
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            user=SimpleNamespace(id=3),
            response=SimpleNamespace(defer=AsyncMock()),
            delete_original_response=AsyncMock(),
        )
        view = MailBulkView(coordinator, "digest-1", 3)

        await view.children[0].callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        organizer.mark_read_all.assert_called_once_with("digest-1")

    async def test_delete_snapshot_acknowledges_as_thinking_before_work(self) -> None:
        organizer = SimpleNamespace(
            digest=Mock(return_value=digest(1)),
            delete_all=Mock(),
        )
        coordinator = SimpleNamespace(
            policy=SimpleNamespace(allows=Mock(return_value=True)),
            organizer=organizer,
            delete_item_messages=AsyncMock(),
            refresh_digest=AsyncMock(),
        )
        interaction = SimpleNamespace(
            guild_id=1,
            channel_id=2,
            user=SimpleNamespace(id=3),
            response=SimpleNamespace(defer=AsyncMock()),
            delete_original_response=AsyncMock(),
        )
        view = MailDeleteAllConfirmationView(coordinator, "digest-1", 3)

        await view.children[0].callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        organizer.delete_all.assert_called_once_with("digest-1")


if __name__ == "__main__":
    unittest.main()
