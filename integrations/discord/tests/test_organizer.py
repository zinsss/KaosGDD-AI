from types import SimpleNamespace
import unittest

from kaos_governor_discord.organizer import MailDigestView, PAGE_SIZE, digest_options, render_digest


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
    def test_digest_renders_markdown_and_pages_select_options(self) -> None:
        value = digest(PAGE_SIZE + 3)
        rendered = render_digest(value, page=1)
        first = digest_options(value, page=0)
        second = digest_options(value, page=1)
        self.assertIn("## Naver Mail Organizer", rendered)
        self.assertIn("2 / 2", rendered)
        self.assertEqual(len(first), PAGE_SIZE)
        self.assertEqual(len(second), 3)
        self.assertEqual(second[0].value, f"item-{PAGE_SIZE}")

    def test_dynamic_option_text_does_not_exceed_discord_limits(self) -> None:
        value = digest(1)
        value["items"]["item-0"]["subject"] = "x" * 300
        value["items"]["item-0"]["sender"] = "y" * 300
        option = digest_options(value)[0]
        self.assertLessEqual(len(option.label), 100)
        self.assertLessEqual(len(option.description), 100)


class DiscordOrganizerViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_digest_components_have_stable_custom_ids(self) -> None:
        coordinator = SimpleNamespace(policy=SimpleNamespace())
        view = MailDigestView(coordinator, "digest-1", digest(PAGE_SIZE + 1))
        custom_ids = [item.custom_id for item in view.children]
        self.assertEqual(len(custom_ids), 5)
        self.assertTrue(all(custom_ids))
        self.assertIn("mail:select:digest-1", custom_ids)
        self.assertIn("mail:next:digest-1", custom_ids)


if __name__ == "__main__":
    unittest.main()
