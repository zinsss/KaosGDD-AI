from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor.calendar import CalendarViewState
from kaosdiscoord.access import AccessPolicy
from kaosdiscoord.calendar import (
    CalendarNavigationView,
    DiscordCalendarState,
    DiscordCalendarSurface,
    FAMILY_EVENT_MARKER,
    FAMILY_EVENT_SUFFIX,
    PERSONAL_EVENT_MARKER,
    agenda_owner_suffix,
    add_months,
    month_markers,
    render_agenda,
    seconds_until_next_midnight,
    visible_month_grid_range,
    weather_agenda_summary,
    weather_by_date,
    weather_marker,
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
    "weather": [
        {
            "date": "2026-08-13",
            "condition": "rain",
            "minTemp": 26,
            "maxTemp": 33,
            "dayparts": [
                {"label": "Morning", "condition": "rain"},
                {"label": "Afternoon", "condition": "cloudy"},
                {"label": "Evening", "condition": "thunderstorm"},
                {"label": "Night", "condition": "clear"},
            ],
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
        self.weather_calls = []

    def bootstrap(self, profile):
        self.profile = profile
        return self.bootstrap_payload

    def month_weather(self, profile, *, start, end, city="pohang"):
        self.weather_calls.append({"profile": profile, "start": start, "end": end, "city": city})
        return {"ok": True, "items": [{"date": "2026-08-13", "glyph": "🌤️", "condition": "partly_cloudy"}]}


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
        self.registered_views = []

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        return self.channel

    def add_view(self, view, *, message_id=None):
        self.registered_views.append((view, message_id))


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
        markers = {item.value: item for item in month_markers(BOOTSTRAP, now=datetime(2026, 8, 13, 9, 0))}

        self.assertTrue(markers[date(2026, 8, 10)].market_day)
        self.assertTrue(markers[date(2026, 8, 13)].duty)
        self.assertEqual(markers[date(2026, 8, 13)].family_events, 1)
        self.assertEqual(markers[date(2026, 8, 13)].zin_events, 1)
        self.assertEqual(markers[date(2026, 8, 13)].tasks, 1)
        self.assertEqual(markers[date(2026, 8, 13)].overdue_tasks, 0)
        self.assertEqual(markers[date(2026, 8, 13)].weather, "🌧️")
        self.assertTrue(markers[date(2026, 8, 15)].public_holiday)

    def test_month_markers_count_overdue_active_tasks(self) -> None:
        bootstrap = {
            **BOOTSTRAP,
            "tasks": [
                {"summary": "Past", "due": "2026-08-13", "dueTime": "08:00", "status": "NEEDS-ACTION"},
                {"summary": "Later", "due": "2026-08-13", "dueTime": "11:00", "status": "NEEDS-ACTION"},
                {"summary": "No time today", "due": "2026-08-13", "status": "NEEDS-ACTION"},
                {"summary": "Done", "due": "2026-08-12", "status": "COMPLETED"},
            ],
        }

        markers = {item.value: item for item in month_markers(bootstrap, now=datetime(2026, 8, 13, 9, 0))}

        self.assertEqual(markers[date(2026, 8, 13)].tasks, 3)
        self.assertEqual(markers[date(2026, 8, 13)].overdue_tasks, 1)

    def test_weather_marker_uses_emoji_or_simple_condition_symbol(self) -> None:
        self.assertEqual(weather_marker({"emoji": "☀", "condition": "rain"}), "☀️")
        self.assertEqual(weather_marker({"glyph": "🌤️", "condition": "cloudy"}), "⛅️")
        self.assertEqual(weather_marker({"glyph": "🌧️"}), "🌧️")
        self.assertEqual(weather_marker({"condition": "rain shower"}), "🌧️")
        self.assertEqual(weather_marker({"summary": "snow"}), "❄️")
        self.assertEqual(weather_marker({"weather": "clear"}), "☀️")
        self.assertEqual(weather_marker({"code": "fog"}), "🌫️")

    def test_visible_month_grid_range_uses_sunday_to_saturday_grid(self) -> None:
        self.assertEqual(visible_month_grid_range(2026, 8), (date(2026, 7, 26), date(2026, 9, 5)))

    def test_weather_by_date_normalizes_agenda_weather(self) -> None:
        self.assertEqual(weather_by_date(BOOTSTRAP), {date(2026, 8, 13): "🌧️"})

    def test_weather_agenda_summary_renders_daily_marker_and_temperatures(self) -> None:
        self.assertEqual(
            weather_agenda_summary(BOOTSTRAP["weather"][0]),
            "🌧️ 26-33℃",
        )
        self.assertEqual(
            weather_agenda_summary({"condition": "cloudy", "minTemp": 1.5, "maxTemp": 8}),
            "⛅️ 1.5-8℃",
        )

    def test_agenda_renders_upcoming_or_single_day_content(self) -> None:
        content = render_agenda(BOOTSTRAP, days=[date(2026, 8, 13)], title="Agenda · 2026.08.13")

        self.assertIn("Agenda", content)
        self.assertIn("# Agenda", content)
        self.assertIn("## 2026.08.13 Thu • 🌧️ 26-33℃", content)
        self.assertNotIn("\n🌧️ ", content)
        self.assertIn("- 09:00 Clinic", content)
        self.assertNotIn("GDD_ZiN", content)
        self.assertIn("- 당직  • 𝘧𝘢𝘮𝘪𝘭𝘺", content)
        self.assertNotIn("**Events**", content)
        self.assertNotIn("Claim review", content)
        self.assertNotIn("Tasks", content)
        self.assertNotIn("Old done", content)

    def test_agenda_owner_suffix_marks_family_and_hides_personal(self) -> None:
        self.assertEqual(agenda_owner_suffix({"owner": "zin", "ownerLabel": "GDD_ZiN"}), "")
        self.assertEqual(agenda_owner_suffix({"owner": "family", "ownerLabel": "Family"}), "  • 𝘧𝘢𝘮𝘪𝘭𝘺")

    def test_event_markers_are_saved(self) -> None:
        self.assertEqual(PERSONAL_EVENT_MARKER, "𝘎𝘋𝘋𝙕𝘪𝙉")
        self.assertEqual(FAMILY_EVENT_MARKER, "𝘧𝘢𝘮𝘪𝘭𝘺")
        self.assertEqual(FAMILY_EVENT_SUFFIX, "  • 𝘧𝘢𝘮𝘪𝘭𝘺")

    def test_agenda_keeps_days_without_events(self) -> None:
        content = render_agenda(
            BOOTSTRAP,
            days=[date(2026, 8, 12), date(2026, 8, 13)],
            title="Agenda · Upcoming 7 Days",
        )

        self.assertIn("2026.08.12", content)
        self.assertIn("2026.08.13", content)
        self.assertNotIn("No items", content)

    def test_agenda_keeps_task_only_days_without_rendering_tasks(self) -> None:
        content = render_agenda(
            {
                **BOOTSTRAP,
                "events": [],
                "tasks": [{"summary": "Task only", "due": "2026-08-13", "status": "NEEDS-ACTION"}],
            },
            days=[date(2026, 8, 13)],
            title="Agenda · Upcoming 7 Days",
        )

        self.assertEqual(
            content,
            "# Agenda · Upcoming 7 Days\n## 2026.08.13 Thu • 🌧️ 26-33℃",
        )

    def test_month_navigation_wraps_years(self) -> None:
        self.assertEqual(add_months(2026, 1, -1), (2025, 12))
        self.assertEqual(add_months(2026, 12, 1), (2027, 1))

    def test_month_navigation_view_has_stable_button_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "calendar.json")
            view = CalendarNavigationView(surface)

        custom_ids = [child.custom_id for child in view.children]
        labels = [child.label for child in view.children]
        self.assertEqual(
            custom_ids,
            ["calendar:month:previous", "calendar:month:today", "calendar:month:next"],
        )
        self.assertEqual(labels, ["<", "Today", ">"])

    async def test_ensure_messages_creates_two_persistent_messages_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "calendar.json"
            channel = FakeChannel()
            surface = self.make_surface(state_path, channel)
            surface.state = DiscordCalendarState(CalendarViewState(2026, 8), month_message_id=0, agenda_message_id=0)

            await surface.ensure_messages(today=date(2026, 8, 13))

            self.assertEqual(len(channel.sent), 2)
            self.assertEqual(channel.sent[0]["content"], "# 2026.08")
            self.assertIn("file", channel.sent[0])
            self.assertIsInstance(channel.sent[0]["view"], CalendarNavigationView)
            self.assertIn("Agenda", channel.sent[1]["content"])
            self.assertTrue(state_path.exists())

    async def test_ensure_messages_fetches_weather_for_visible_month_grid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = FakeAdapter()
            surface = DiscordCalendarSurface(
                FakeBot(FakeChannel()),  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=Path(temporary) / "calendar.json",
                adapter=adapter,  # type: ignore[arg-type]
            )
            surface.state = DiscordCalendarState(CalendarViewState(2026, 8), month_message_id=0, agenda_message_id=0)

            await surface.ensure_messages(today=date(2026, 8, 13))

            self.assertEqual(
                adapter.weather_calls,
                [{"profile": "main", "start": "2026-07-26", "end": "2026-09-05", "city": "pohang"}],
            )

    async def test_month_navigation_updates_month_and_reuses_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "calendar.json"
            channel = FakeChannel()
            bot = FakeBot(channel)
            surface = DiscordCalendarSurface(
                bot,  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=state_path,
                adapter=FakeAdapter(),  # type: ignore[arg-type]
            )
            surface.state = DiscordCalendarState(CalendarViewState(2026, 8), month_message_id=0, agenda_message_id=0)

            await surface.ensure_messages(today=date(2026, 8, 13))
            month_id = surface.state.month_message_id
            agenda_id = surface.state.agenda_message_id
            bot.registered_views = []
            await surface.navigate_month("next", today=date(2026, 8, 13))

            self.assertEqual(surface.state.view.visible_year, 2026)
            self.assertEqual(surface.state.view.visible_month, 9)
            self.assertEqual(surface.state.view.agenda_mode, "upcoming")
            self.assertEqual(surface.state.month_message_id, month_id)
            self.assertEqual(surface.state.agenda_message_id, agenda_id)
            self.assertIn("2026.09", channel.messages[month_id].edits[-1]["content"])
            self.assertIn((channel.messages[month_id].edits[-1]["view"], month_id), bot.registered_views)

    async def test_midnight_refresh_resets_to_new_today(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "calendar.json"
            channel = FakeChannel()
            surface = self.make_surface(state_path, channel)
            surface.state = DiscordCalendarState(
                CalendarViewState(2026, 9, agenda_mode="day", agenda_date=date(2026, 9, 17)),
                month_message_id=0,
                agenda_message_id=0,
            )

            await surface.ensure_messages(today=date(2026, 8, 31))
            month_id = surface.state.month_message_id
            agenda_id = surface.state.agenda_message_id
            await surface.refresh_for_new_day(today=date(2026, 9, 1))

            self.assertEqual(surface.state.view.visible_year, 2026)
            self.assertEqual(surface.state.view.visible_month, 9)
            self.assertEqual(surface.state.view.agenda_mode, "upcoming")
            self.assertIsNone(surface.state.view.agenda_date)
            self.assertEqual(surface.state.month_message_id, month_id)
            self.assertEqual(surface.state.agenda_message_id, agenda_id)
            self.assertIn("2026.09", channel.messages[month_id].edits[-1]["content"])
            self.assertIn("Upcoming 7 Days", channel.messages[agenda_id].edits[-1]["content"])

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

    def test_seconds_until_next_midnight_uses_local_date_boundary(self) -> None:
        self.assertEqual(
            seconds_until_next_midnight(datetime(2026, 8, 13, 23, 59, 30, tzinfo=timezone.utc)),
            30,
        )
        self.assertEqual(
            seconds_until_next_midnight(datetime(2026, 8, 13, 0, 0, 0, tzinfo=timezone.utc)),
            24 * 60 * 60,
        )


if __name__ == "__main__":
    unittest.main()
