import importlib.util
import pathlib
import unittest


SERVER_PATH = pathlib.Path(__file__).resolve().parents[1] / "apps" / "calendar-adapter" / "server.py"
SPEC = importlib.util.spec_from_file_location("calendar_adapter_server", SERVER_PATH)
calendar_adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(calendar_adapter)


class CalendarAdapterSmartEventParserTests(unittest.TestCase):
    def test_splits_natural_day_note_separators(self) -> None:
        events = calendar_adapter.parse_family_smart_event_text(
            "연차, 12:30 메롱 그리고 2:30 스파예가 + 18:00 저녁",
            "2026-09-03",
        )

        self.assertEqual([event["title"] for event in events], ["연차", "메롱", "스파예가", "저녁"])
        self.assertTrue(events[0]["allDay"])
        self.assertEqual(events[1]["startTime"], "12:30")
        self.assertEqual(events[1]["endTime"], "13:30")
        self.assertEqual(events[2]["startTime"], "14:30")
        self.assertEqual(events[3]["startTime"], "18:00")

    def test_keeps_explicit_time_range_with_dash(self) -> None:
        events = calendar_adapter.parse_family_smart_event_text(
            "연차 / 12:30-14:00 메롱",
            "2026-09-03",
        )

        self.assertEqual([event["title"] for event in events], ["연차", "메롱"])
        self.assertEqual(events[1]["startTime"], "12:30")
        self.assertEqual(events[1]["endTime"], "14:00")


if __name__ == "__main__":
    unittest.main()
