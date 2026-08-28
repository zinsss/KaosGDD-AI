from datetime import date, datetime, time
from pathlib import Path
import tempfile
import unittest

from kaos_governor.daily_digest import (
    DailyDigestConfig,
    DailyDigestError,
    DailyDigestService,
    KST,
    render_daily_digest,
)


class Adapter:
    def __init__(self) -> None:
        self.weather_calls = []

    def bootstrap(self, profile):
        self.profile = profile
        return {
            "live": True,
            "events": [
                {"summary": "전주", "startDate": "2026-08-29", "startTime": ""},
                {"summary": "Tomorrow", "startDate": "2026-08-30", "startTime": "09:00"},
            ],
            "tasks": [
                {"summary": "Call office", "due": "2026-08-29", "dueTime": "10:00", "status": "NEEDS-ACTION"},
                {"summary": "Done", "due": "2026-08-29", "dueTime": "08:00", "status": "COMPLETED"},
            ],
        }

    def month_weather(self, profile, *, start, end, city):
        self.weather_calls.append((profile, start, end, city))
        return {
            "items": [
                {
                    "date": "2026-08-29",
                    "glyph": "🌧️",
                    "condition": "rain",
                    "minTemp": 23,
                    "maxTemp": 30,
                }
            ]
        }


class DailyDigestTests(unittest.TestCase):
    def config(self, root: Path) -> DailyDigestConfig:
        return DailyDigestConfig(
            enabled=True,
            send_time=time(7, 0),
            profile="main",
            weather_city="pohang",
            state_path=root / "daily-digest.json",
            content_cache_path=root / "daily-content.json",
            poll_seconds=30,
            max_items=5,
        )

    def test_configuration_validates_time_profile_and_city(self) -> None:
        config = DailyDigestConfig.from_env(
            {
                "DAILY_DIGEST_ENABLED": "true",
                "DAILY_DIGEST_TIME": "07:00",
                "DAILY_DIGEST_PROFILE": "main",
                "DAILY_DIGEST_WEATHER_CITY": "pohang",
            }
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.send_time, time(7, 0))

        with self.assertRaisesRegex(DailyDigestError, "HH:MM"):
            DailyDigestConfig.from_env({"DAILY_DIGEST_TIME": "7am"})
        with self.assertRaisesRegex(DailyDigestError, "main or family"):
            DailyDigestConfig.from_env({"DAILY_DIGEST_PROFILE": "admin"})
        with self.assertRaisesRegex(DailyDigestError, "WEATHER_CITY"):
            DailyDigestConfig.from_env({"DAILY_DIGEST_WEATHER_CITY": "../../etc"})
        with self.assertRaisesRegex(DailyDigestError, "HTTPS URL"):
            DailyDigestConfig.from_env({"DAILY_DIGEST_PORTAL_URL": "http://kaosgdd.net"})

    def test_renderer_matches_requested_structure_and_empty_sections(self) -> None:
        rendered = render_daily_digest(
            day=date(2026, 8, 29),
            weather={"glyph": "🌧️", "condition": "rain", "minTemp": 23, "maxTemp": 30},
            events=[],
            tasks=[],
        )

        self.assertTrue(rendered.startswith("# 2026.08.29(Sat)\n* 🌧️ rain 23-30°C"))
        self.assertIn("### 일일 성경 말씀", rendered)
        self.assertIn("### 일일 힘을 주는 명언", rendered)
        self.assertIn("### Events\n-\n\n### Tasks\n-", rendered)
        self.assertLessEqual(len(rendered), 1024)

    def test_build_uses_live_profile_weather_and_only_today_active_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = Adapter()
            service = DailyDigestService(self.config(Path(temporary)), adapter)  # type: ignore[arg-type]

            rendered = service.build(date(2026, 8, 29))

        self.assertEqual(service.adapter.profile, "main")  # type: ignore[attr-defined]
        self.assertEqual(
            adapter.weather_calls,
            [("main", "2026-08-29", "2026-08-29", "pohang")],
        )
        self.assertIn("- 전주", rendered)
        self.assertNotIn("Tomorrow", rendered)
        self.assertIn("- 10:00 Call office", rendered)
        self.assertNotIn("Done", rendered)

    def test_renderer_keeps_both_sections_with_many_long_items(self) -> None:
        items = [
            {"summary": f"Item {index} " + "x" * 100, "startTime": "09:00", "dueTime": "10:00"}
            for index in range(20)
        ]
        rendered = render_daily_digest(
            day=date(2026, 8, 29),
            weather={"glyph": "🌧️", "condition": "rain", "minTemp": 23, "maxTemp": 30},
            events=items,
            tasks=items,
            max_items=20,
        )

        self.assertLessEqual(len(rendered), 1024)
        self.assertIn("### Events", rendered)
        self.assertIn("### Tasks", rendered)

    def test_first_start_after_send_time_baselines_today_then_sends_next_day(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = DailyDigestService(self.config(Path(temporary)), Adapter())  # type: ignore[arg-type]
            first_start = datetime(2026, 8, 28, 18, 0, tzinfo=KST)
            next_morning = datetime(2026, 8, 29, 7, 0, tzinfo=KST)

            service.initialize(first_start)
            same_day_due = service.is_due(first_start)
            next_day_due = service.is_due(next_morning)
            service.record_sent(next_morning.date(), message_id=501)
            after_send_due = service.is_due(next_morning)
            status = service.status()

        self.assertFalse(same_day_due)
        self.assertTrue(next_day_due)
        self.assertFalse(after_send_due)
        self.assertEqual(status["lastSentDate"], "2026-08-29")
        self.assertEqual(status["lastMessageId"], "501")

    def test_first_start_before_send_time_becomes_due_at_send_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = DailyDigestService(self.config(Path(temporary)), Adapter())  # type: ignore[arg-type]
            service.initialize(datetime(2026, 8, 29, 6, 30, tzinfo=KST))

            before = service.is_due(datetime(2026, 8, 29, 6, 59, tzinfo=KST))
            at_time = service.is_due(datetime(2026, 8, 29, 7, 0, tzinfo=KST))

        self.assertFalse(before)
        self.assertTrue(at_time)

    def test_bible_and_quote_cycle_through_available_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = DailyDigestService(self.config(Path(temporary)), Adapter())  # type: ignore[arg-type]
            rendered = service.build(date(2026, 8, 29))

            next_bible = service.cycle_content(rendered, "bible")
            next_quote = service.cycle_content(rendered, "quote")

        self.assertNotEqual(rendered, next_bible)
        self.assertNotEqual(rendered, next_quote)
        self.assertEqual(next_bible.count("### 일일 성경 말씀"), 1)
        self.assertEqual(next_quote.count("### 일일 힘을 주는 명언"), 1)

    def test_weather_url_opens_existing_portal_detail_for_digest_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = DailyDigestService(self.config(Path(temporary)), Adapter())  # type: ignore[arg-type]

            url = service.weather_url(date(2026, 8, 29))

        self.assertEqual(url, "https://kaosgdd.net/#/calendar?weather=2026-08-29")


if __name__ == "__main__":
    unittest.main()
