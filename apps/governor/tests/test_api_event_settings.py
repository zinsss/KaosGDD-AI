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


if __name__ == "__main__":
    unittest.main()
