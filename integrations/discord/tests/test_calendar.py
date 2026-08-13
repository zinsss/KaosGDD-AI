from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor.calendar import CalendarViewState
from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.calendar import (
    DiscordCalendarState,
    DiscordCalendarSurface,
    month_markers,
    render_agenda,
)


BOOTSTRAP = {
    "live": True,
    "collections": [
        {"id": "zin:calendar", "owner": "zin", "ownerLabel": "GDD_ZiN"},
        {"id": "family:calendar", "owner": "family", "ownerLabel": "Family"},
    ],
    "events": [
        {
            "summary": "Market Day",
            "startDate": "2026-08-10",
            "collection": "zin:calendar",
            "categories": ["KAOS-MARKET-DAY"],
        },
        {
            "summary": "당직",
            "startDate": "2026-08-13",
            "collection": "family:calendar",
            "categories": [],
        },
        {
            "summary": "Clinic",
            "startDate": "2026-08-13",
            "startTime": "09:00",
            "collection": "zin:calendar",
            "categories": [],
        },
        {
            "summary": "쉬는 날",
            "startDate": "2026-08-15",
            "collection": "family:calendar",
            "publicHoliday": True,
            "categories": [],
        },
    ],
    "tasks": [
        {"summary": "Claim review", "due": "2026-08-13", "status": "NEEDS-ACTION"},
        {"summary": "Old done", "due": "2026-08-13", "status": "COMPLETED"},
    ],
}


class FakeAdapter:
    def __init__(self, bootstrap=BOOTSTRAP):
        self.bootstrap_payload = bootstrap

    def bootstrap(self, profile):
        self.profile = profile
        return self.bootstrap_payload


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
        self.next_id = 500

    async def send(self, **kwargs):
        message = FakeMessage(self.next_id)
        self.next_id += 1
        message.sent = kwargs
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


class DiscordCalendarTests(unittest.IsolatedAsyncioTestCase):
    def make_surface(self, path: Path, channel: FakeChannel | None = None) -> DiscordCalendarSurface:
        channel = channel or FakeChannel()
        return DiscordCalendarSurface(
            FakeBot(channel),  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            profile="main",
            state_path=path,
            adapter=FakeAdapter(),  # type: ignore[arg-type]
        )

    def test_month_markers_follow_legacy_marker_contract(self) -> None:
        markers = {item.value: item for item in month_markers(BOOTSTRAP)}

        self.assertTrue(markers[date(2026, 8, 10)].market_day)
        self.assertTrue(markers[date(2026, 8, 13)].duty)
        self.assertEqual(markers[date(2026, 8, 13)].family_events, 1)
        self.assertEqual(markers[date(2026, 8, 13)].zin_events, 1)
        self.assertEqual(markers[date(2026, 8, 13)].tasks, 1)
        self.assertTrue(markers[date(2026, 8, 15)].public_holiday)

    def test_agenda_renders_upcoming_or_single_day_content(self) -> None:
        content = render_agenda(BOOTSTRAP, days=[date(2026, 8, 13)], title="Agenda · 2026.08.13")

        self.assertIn("Agenda", content)
        self.assertIn("Clinic", content)
        self.assertIn("Claim review", content)
        self.assertNotIn("Old done", content)

    async def test_ensure_messages_creates_two_persistent_messages_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "calendar.json"
            channel = FakeChannel()
            surface = self.make_surface(state_path, channel)

            await surface.ensure_messages(today=date(2026, 8, 13))

            self.assertEqual(len(channel.sent), 2)
            self.assertIn("Calendar", channel.sent[0]["content"])
            self.assertIn("file", channel.sent[0])
            self.assertIn("Agenda", channel.sent[1]["content"])
            self.assertTrue(state_path.exists())

    async def test_valid_day_command_updates_month_agenda_and_deletes_user_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "calendar.json")
            surface.state = DiscordCalendarState(CalendarViewState(2026, 8), month_message_id=0, agenda_message_id=0)
            message = SimpleNamespace(
                id=42,
                content="9.17",
                channel=SimpleNamespace(id=300),
                guild=SimpleNamespace(id=100),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            handled = await surface.handle_message(message, today=date(2026, 8, 13))  # type: ignore[arg-type]

            self.assertTrue(handled)
            self.assertEqual(surface.state.view.visible_month, 9)
            self.assertEqual(surface.state.view.agenda_date, date(2026, 9, 17))
            message.delete.assert_awaited_once()

    async def test_invalid_calendar_message_is_deleted_without_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "calendar.json")
            message = SimpleNamespace(
                id=42,
                content="99",
                channel=SimpleNamespace(id=300),
                guild=SimpleNamespace(id=100),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            handled = await surface.handle_message(message, today=date(2026, 8, 13))  # type: ignore[arg-type]

            self.assertTrue(handled)
            self.assertEqual(surface.state.view.agenda_mode, "upcoming")
            message.delete.assert_awaited_once()

    async def test_own_calendar_messages_are_not_deleted_before_state_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "calendar.json")
            message = SimpleNamespace(
                id=700,
                content="Calendar",
                channel=SimpleNamespace(id=300),
                guild=SimpleNamespace(id=100),
                author=SimpleNamespace(id=900, bot=True),
                delete=AsyncMock(),
            )

            handled = await surface.handle_message(message, today=date(2026, 8, 13))  # type: ignore[arg-type]

            self.assertTrue(handled)
            message.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
