from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_governor.memos import Memo
from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.memos import DiscordMemosCapture


class FakeMemos:
    def __init__(self) -> None:
        self.created = []

    def create(self, content):
        self.created.append(content)
        return Memo("memos/42", content, ("태그",), "created", "updated", "PRIVATE", False)


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

    async def test_plain_message_creates_memo_then_deletes_original(self) -> None:
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
        self.assertEqual(service.created, ["메모 내용\n#태그"])
        message.delete.assert_awaited_once()
        self.assertEqual(message.channel.sent[0][0], ("Saved to Memos: memos/42",))
        self.assertEqual(message.channel.sent[0][1]["delete_after"], 1)
        self.assertEqual(capture.status()["acceptedCount"], 1)

    async def test_other_channels_are_ignored(self) -> None:
        service = FakeMemos()
        capture = DiscordMemosCapture(
            service,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
        )

        self.assertFalse(await capture.handle_message(self.make_message("memo", channel_id=301)))  # type: ignore[arg-type]
        self.assertEqual(service.created, [])


if __name__ == "__main__":
    unittest.main()
