from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_governor.memos import Memo, MemoSearchPage, MemoSearchResult
from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.memos import (
    DiscordMemosCapture,
    MemosCreatePromptView,
    parse_create_memo_message,
    render_memo_opened,
)


class FakeMemos:
    def __init__(self) -> None:
        self.created = []
        self.searches = []
        self.config = SimpleNamespace(max_results=20)

    def create(self, content):
        self.created.append(content)
        return Memo("memos/42", content, ("태그",), "created", "updated", "PRIVATE", False)

    def search(self, query, tags, limit):
        self.searches.append((query, tags, limit))
        content = "# Rustdesk Settings\n## For Tailscale\n- Relay server: 100.94.208.16\n@everyone"
        memo = Memo("memos/99", content, ("office",), "created", "updated", "PRIVATE", False)
        return [MemoSearchResult(memo, "Rustdesk Settings")]

    def search_page(self, query, tags, limit):
        self.searches.append((query, tags, limit))
        first = Memo(
            "memos/99",
            "# Rustdesk Settings\n## For Tailscale\n- Relay server: 100.94.208.16\n@everyone",
            ("office",),
            "created",
            "updated",
            "PRIVATE",
            False,
        )
        second = Memo(
            "memos/100",
            "## Rustdesk LAN\n- API server: blank",
            ("office",),
            "created",
            "updated",
            "PRIVATE",
            False,
        )
        return MemoSearchPage(
            query,
            (),
            (MemoSearchResult(first, "Rustdesk Settings"), MemoSearchResult(second, "Rustdesk LAN")),
            13,
            213,
        )


class FakeChannel:
    def __init__(self) -> None:
        self.id = 300
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return SimpleNamespace(id=900)


class DiscordMemosCaptureTests(unittest.IsolatedAsyncioTestCase):
    def make_message(self, content: str, *, channel_id: int = 300):
        channel = FakeChannel()
        channel.id = channel_id
        message = SimpleNamespace(
            id=500,
            content=content,
            guild=SimpleNamespace(id=100),
            channel=channel,
            author=SimpleNamespace(id=200, bot=False),
            delete=AsyncMock(),
            reply=AsyncMock(),
        )
        return message

    async def test_plain_message_is_deleted_without_creating_memo(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            confirmation_delete_after=1,
        )
        message = self.make_message("메모 내용\n#태그")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, [])
        message.delete.assert_awaited_once()
        self.assertEqual(message.channel.sent, [])
        self.assertEqual(capture.status()["acceptedCount"], 0)

    async def test_triple_plus_message_creates_memo_then_deletes_original(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            confirmation_delete_after=1,
        )
        message = self.make_message("+++\n### 메모 내용\n#태그")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, ["### 메모 내용\n#태그"])
        message.delete.assert_awaited_once()
        self.assertEqual(message.channel.sent[0][0], ("Saved to Memos: memos/42",))
        self.assertEqual(message.channel.sent[0][1]["delete_after"], 1)
        self.assertEqual(capture.status()["acceptedCount"], 1)

    async def test_triple_plus_only_posts_modal_button_prompt(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        message = self.make_message("+++")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, [])
        message.delete.assert_awaited_once()
        self.assertEqual(message.channel.sent[0][0], ("## Memos\n- Add memo",))
        self.assertIsInstance(message.channel.sent[0][1]["view"], MemosCreatePromptView)

    async def test_dotdot_message_searches_memos_then_deletes_original(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        message = self.make_message("..printer")

        handled = await capture.handle_message(message)  # type: ignore[arg-type]

        self.assertTrue(handled)
        self.assertEqual(service.created, [])
        self.assertEqual(service.searches, [("printer", None, 20)])
        message.delete.assert_awaited_once()
        content = message.channel.sent[0][0][0]
        self.assertIn("Searched..", content)
        self.assertIn("## printer", content)
        self.assertIn("13 results in 213 memos", content)
        self.assertIn("view", message.channel.sent[0][1])

    async def test_dotdot_message_normalizes_multi_term_memos_search(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )
        message = self.make_message("..rust   desk setup")

        self.assertTrue(await capture.handle_message(message))  # type: ignore[arg-type]

        self.assertEqual(service.searches, [("rust desk setup", None, 20)])
        content = message.channel.sent[0][0][0]
        self.assertIn("## rust desk setup", content)

    async def test_other_channels_are_ignored(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )

        self.assertFalse(await capture.handle_message(self.make_message("memo", channel_id=301)))  # type: ignore[arg-type]
        self.assertEqual(service.created, [])

    def test_opened_memo_renders_body_as_markdown_and_escapes_mentions(self) -> None:
        memo = Memo(
            "memos/99",
            "# Rustdesk Settings\n## For Tailscale\n- Relay server: 100.94.208.16\n@everyone",
            (),
            "",
            "",
            "PRIVATE",
            False,
        )
        content = render_memo_opened("rustdesk", MemoSearchResult(memo, "Rustdesk Settings"))

        self.assertIn("# Rustdesk Settings\n## For Tailscale", content)
        self.assertIn("- Relay server: 100.94.208.16", content)
        self.assertIn("@\u200beveryone", content)

    def test_parse_create_memo_message_requires_triple_plus_marker(self) -> None:
        self.assertEqual(parse_create_memo_message("+++"), "")
        self.assertEqual(parse_create_memo_message("+++\n# Title\nBody"), "# Title\nBody")
        self.assertEqual(parse_create_memo_message("  +++  \n# Title"), "# Title")
        self.assertIsNone(parse_create_memo_message("plain memo"))
        self.assertIsNone(parse_create_memo_message("+++ # Title"))


if __name__ == "__main__":
    unittest.main()
