from __future__ import annotations

import unittest
from unittest.mock import patch

from kaos_governor import api


class EventPresetApiTests(unittest.TestCase):
    def test_event_preset_id_matches_only_expected_route(self) -> None:
        self.assertEqual(api.event_preset_id("/api/event-presets/abc-123"), "abc-123")
        self.assertEqual(api.event_preset_id("/api/event-presets/ABC"), "")
        self.assertEqual(api.event_preset_id("/api/event-presets/abc-123/extra"), "")

    def test_normalized_event_preset_preserves_family_contract(self) -> None:
        preset = api._normalize_event_preset(
            {
                "id": "preset-1",
                "name": "당직",
                "title": "당직",
                "owner": "family",
                "allDay": True,
                "startTime": "09:00:00",
                "endTime": "10:00:00",
                "memo": "note",
            }
        )

        self.assertEqual(preset["id"], "preset-1")
        self.assertEqual(preset["owner"], "family")
        self.assertTrue(preset["shareFamily"])
        self.assertEqual(preset["startTime"], "09:00")
        self.assertEqual(preset["endTime"], "10:00")

    def test_list_event_presets_filters_personal_items_from_family_profile(self) -> None:
        store = {
            "items": [
                {"id": "family-1", "name": "가족", "title": "가족", "owner": "family"},
                {"id": "zin-1", "name": "개인", "title": "개인", "owner": "zin"},
            ]
        }
        with patch.object(api, "_read_setting", return_value=(store, 1)):
            payload = api.list_event_presets("family")

        self.assertEqual([item["id"] for item in payload["items"]], ["family-1"])

    def test_custom_event_settings_update_mirrors_generated_flags_to_adapter(self) -> None:
        mirrored: list[dict[str, object]] = []

        class FakeCalendarAdapter:
            def mirror_custom_event_settings(self, payload: dict[str, object]) -> dict[str, object]:
                mirrored.append(payload)
                return {"sync": {"ok": True}}

        with (
            patch.object(api, "_read_setting", return_value=({"marketDaysEnabled": True, "claimDayEnabled": True}, 1)),
            patch.object(api, "_write_setting", return_value=({"marketDaysEnabled": False, "claimDayEnabled": True}, 2)),
            patch.object(api, "CalendarAdapterClient", FakeCalendarAdapter),
        ):
            payload = api.update_custom_event_settings({"marketDaysEnabled": False})

        self.assertEqual(payload["version"], 2)
        self.assertEqual(mirrored, [{"marketDaysEnabled": False, "claimDayEnabled": True}])

    def test_custom_event_sync_flattens_adapter_sync_payload(self) -> None:
        mirrored: list[dict[str, object]] = []

        class FakeCalendarAdapter:
            def mirror_custom_event_settings(self, payload: dict[str, object]) -> dict[str, object]:
                mirrored.append(payload)
                return {"sync": {"ok": True}}

            def sync_custom_events(self) -> dict[str, object]:
                return {"ok": True, "total": 2, "unchanged": 2}

        with (
            patch.object(api, "_read_setting", return_value=({"marketDaysEnabled": True, "claimDayEnabled": False}, 1)),
            patch.object(api, "CalendarAdapterClient", FakeCalendarAdapter),
        ):
            payload = api.sync_custom_events()

        self.assertEqual(payload["sync"], {"ok": True, "total": 2, "unchanged": 2})
        self.assertEqual(mirrored, [{"marketDaysEnabled": True, "claimDayEnabled": False}])

    def test_weather_settings_are_profile_scoped(self) -> None:
        reads: list[tuple[str, str]] = []
        writes: list[tuple[str, str, dict[str, object]]] = []

        def fake_read(scope: str, name: str, default: dict[str, object]) -> tuple[dict[str, object], int]:
            reads.append((scope, name))
            return ({"location": "daegu"} if scope == "family" else dict(default), 3)

        def fake_write(scope: str, name: str, payload: dict[str, object]) -> tuple[dict[str, object], int]:
            writes.append((scope, name, payload))
            return payload, 4

        with patch.object(api, "_read_setting", side_effect=fake_read):
            family_payload = api.weather_settings_payload("family")
            main_payload = api.weather_settings_payload("main")

        self.assertEqual(family_payload["settings"], {"location": "daegu"})
        self.assertEqual(main_payload["settings"], {"location": "pohang"})
        self.assertEqual(reads, [("family", "weather"), ("personal", "weather")])

        with (
            patch.object(api, "_read_setting", return_value=({"location": "pohang"}, 1)),
            patch.object(api, "_write_setting", side_effect=fake_write),
        ):
            saved = api.update_weather_settings({"location": "yeonghae"}, "family")

        self.assertEqual(saved["settings"], {"location": "yeonghae"})
        self.assertEqual(writes, [("family", "weather", {"location": "yeonghae"})])

    def test_weather_settings_reject_invalid_location(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_weather_location"):
            api._normalize_weather_settings({"location": "seoul"})

    def test_settings_status_summarizes_governor_backed_family_settings(self) -> None:
        recurring_payload = {
            "ok": True,
            "items": [
                {
                    "id": "weekly-1",
                    "title": "인플루엔자 신고",
                    "enabled": True,
                    "owner": "family",
                    "shareFamily": True,
                    "creationPolicy": "on_schedule",
                    "frequency": "weekly",
                    "firstDueDate": "2026-08-03",
                    "dueTime": "10:00",
                    "activeUid": "KAOSGDD-REPEAT-1",
                    "activeDueDate": "2026-08-03",
                    "nextDueDate": "",
                    "lastCompletedAt": "",
                    "error": "",
                },
                {
                    "id": "weekly-2",
                    "title": "완료 후 생성",
                    "enabled": False,
                    "owner": "zin",
                    "shareFamily": False,
                    "creationPolicy": "on_completion",
                    "frequency": "weekly",
                    "firstDueDate": "2026-08-10",
                    "dueTime": "10:00",
                    "activeUid": "",
                    "activeDueDate": "",
                    "nextDueDate": "2026-08-17",
                    "lastCompletedAt": "2026-08-11T00:00:00Z",
                    "error": "temporary_failure",
                },
            ],
        }
        presets_payload = {
            "ok": True,
            "items": [
                {"id": "preset-1", "owner": "family", "name": "당직", "title": "당직"},
                {"id": "preset-2", "owner": "zin", "name": "개인", "title": "개인"},
            ],
        }

        def fake_read(scope: str, name: str, default: dict[str, object]) -> tuple[dict[str, object], int]:
            if (scope, name) == ("family", "weather"):
                return {"location": "yeongcheon"}, 7
            if (scope, name) == ("system", "generated-calendar"):
                return {"marketDaysEnabled": True, "claimDayEnabled": False}, 3
            return dict(default), 0

        with (
            patch.object(api, "_read_setting", side_effect=fake_read),
            patch.object(api, "list_recurring_tasks", return_value=recurring_payload),
            patch.object(api, "list_event_presets", return_value=presets_payload),
        ):
            payload = api.settings_status_payload("family")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["profile"], "family")
        self.assertEqual(payload["weather"]["location"], "yeongcheon")
        self.assertEqual(payload["weather"]["locationLabel"], "영천")
        self.assertTrue(payload["generatedCalendar"]["marketDaysEnabled"])
        self.assertFalse(payload["generatedCalendar"]["claimDayEnabled"])
        self.assertFalse(payload["generatedCalendar"]["editable"])
        self.assertEqual(payload["generatedCalendar"]["marketDayPolicy"], "매월 5, 10, 15, 20, 25, 30일")
        self.assertEqual(payload["eventPresets"]["count"], 2)
        self.assertEqual(payload["eventPresets"]["familyCount"], 1)
        self.assertEqual(payload["recurringTasks"]["count"], 2)
        self.assertEqual(payload["recurringTasks"]["enabledCount"], 1)
        self.assertEqual(payload["recurringTasks"]["onScheduleCount"], 1)
        self.assertEqual(payload["recurringTasks"]["onCompletionCount"], 1)
        self.assertEqual(payload["recurringTasks"]["items"][0]["title"], "인플루엔자 신고")
        self.assertTrue(payload["recurringTasks"]["items"][0]["active"])
        self.assertEqual(payload["recurringTasks"]["items"][1]["lastError"], "temporary_failure")


if __name__ == "__main__":
    unittest.main()
