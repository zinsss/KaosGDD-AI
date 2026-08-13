from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest

from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.system_status import (
    DiscordServiceStatusSurface,
    SERVICES,
    ServiceStatusView,
    render_service_message,
)


class FakeMessage:
    def __init__(self, message_id):
        self.id = message_id
        self.edits = []
        self.deleted = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        return self

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.messages = {}
        self.next_id = 700

    async def send(self, **kwargs):
        message = FakeMessage(self.next_id)
        self.next_id += 1
        self.sent.append(kwargs)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


class FakeBot:
    def __init__(self, channel):
        self.channel = channel
        self.user = SimpleNamespace(id=900)

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        return self.channel


class DiscordServiceStatusTests(unittest.IsolatedAsyncioTestCase):
    def make_surface(self, path: Path, channel: FakeChannel | None = None) -> DiscordServiceStatusSurface:
        channel = channel or FakeChannel()
        return DiscordServiceStatusSurface(
            FakeBot(channel),  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            state_path=path,
        )

    def test_service_rows_match_requested_buttons(self) -> None:
        labels = [item.label for item in SERVICES]

        self.assertEqual(
            labels,
            [
                "KaosBrain",
                "KaosGovernor",
                "KaosPACS",
                "KaosInj",
                "Radicale",
                "Memos",
                "Paperless",
                "StirlingPDF",
                "Vaultwarden",
                "Rustdesk",
            ],
        )
        self.assertEqual(SERVICES[0].description, "Brain of KaosGDD on Odroid H4 Ultra")
        self.assertEqual(SERVICES[1].description, "Rules and controller of KaosGDD")

    async def test_ensure_message_creates_one_status_message_per_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 10)
            self.assertEqual(channel.sent[0]["content"], render_service_message(SERVICES[0]))
            self.assertIsInstance(channel.sent[0]["view"], ServiceStatusView)
            buttons = channel.sent[0]["view"].children
            self.assertEqual(len(buttons), 1)
            self.assertEqual(buttons[0].label, "Healthy")
            self.assertFalse(buttons[0].disabled)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["messageIds"]["kaosbrain"], 700)
            self.assertEqual(state["messageIds"]["rustdesk"], 709)

    async def test_ensure_message_edits_existing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            message = FakeMessage(777)
            channel.messages[777] = message
            path = Path(temporary) / "status.json"
            path.write_text('{"messageIds": {"kaosbrain": 777}}', encoding="utf-8")
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 9)
            self.assertEqual(len(message.edits), 1)
            self.assertEqual(message.edits[0]["content"], render_service_message(SERVICES[0]))

    async def test_ensure_message_deletes_legacy_combined_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            legacy = FakeMessage(777)
            channel.messages[777] = legacy
            path = Path(temporary) / "status.json"
            path.write_text('{"messageId": 777}', encoding="utf-8")
            surface = self.make_surface(path, channel)

            await surface.ensure_message()

            self.assertTrue(legacy.deleted)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("messageId", state)
            self.assertEqual(len(state["messageIds"]), 10)

    async def test_restart_request_is_recorded_for_future_down_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.json"
            surface = self.make_surface(path)

            await surface.request_restart("memos")
            await surface.request_restart("memos")

            self.assertEqual(surface.status()["restartRequests"], {"memos": 2})


if __name__ == "__main__":
    unittest.main()
