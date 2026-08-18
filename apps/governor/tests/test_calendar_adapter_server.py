from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


def load_server_module():
    test_path = Path(__file__).resolve()
    candidates = [test_path.parents[1] / "calendar-adapter" / "server.py"]
    if len(test_path.parents) > 3:
        candidates.append(test_path.parents[3] / "apps" / "calendar-adapter" / "server.py")
    path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    spec = importlib.util.spec_from_file_location("kaos_calendar_adapter_server", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("calendar_adapter_server_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CalendarAdapterServerTests(unittest.TestCase):
    def test_completed_vtodo_sets_ios_visible_completion_fields_and_preserves_unknown_properties(self) -> None:
        server = load_server_module()
        existing = {
            "UID": "TASK-1",
            "CREATED": "20260818T000000Z",
            "SEQUENCE": "4",
            "STATUS": "NEEDS-ACTION",
            "_raw_properties": [
                "UID:TASK-1",
                "STATUS:NEEDS-ACTION",
                "PERCENT-COMPLETE:0",
                "X-APPLE-SORT-ORDER:123",
            ],
        }

        _uid, body = server.build_vtodo({"uid": "TASK-1", "title": "Check", "status": "COMPLETED"}, existing)

        self.assertIn("STATUS:COMPLETED", body)
        self.assertIn("COMPLETED:", body)
        self.assertIn("PERCENT-COMPLETE:100", body)
        self.assertIn("SEQUENCE:5", body)
        self.assertIn("X-APPLE-SORT-ORDER:123", body)

    def test_reopened_vtodo_removes_completed_timestamp_and_sets_zero_percent(self) -> None:
        server = load_server_module()
        existing = {
            "UID": "TASK-1",
            "CREATED": "20260818T000000Z",
            "SEQUENCE": "4",
            "STATUS": "COMPLETED",
            "COMPLETED": "20260818T010000Z",
            "_raw_properties": [
                "UID:TASK-1",
                "STATUS:COMPLETED",
                "COMPLETED:20260818T010000Z",
                "PERCENT-COMPLETE:100",
                "X-APPLE-SORT-ORDER:123",
            ],
        }

        _uid, body = server.build_vtodo({"uid": "TASK-1", "title": "Check", "status": "NEEDS-ACTION"}, existing)

        self.assertIn("STATUS:NEEDS-ACTION", body)
        self.assertIn("PERCENT-COMPLETE:0", body)
        self.assertIn("SEQUENCE:5", body)
        self.assertIn("X-APPLE-SORT-ORDER:123", body)
        self.assertNotIn("COMPLETED:20260818T010000Z", body)

    def test_event_presets_crud_uses_family_scope(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temporary:
            server.EVENT_PRESETS_FILE = str(Path(temporary) / "event-presets.json")

            created = server.upsert_event_preset(
                {
                    "name": "당직",
                    "title": "당직",
                    "allDay": True,
                    "memo": "family preset",
                    "shareFamily": True,
                },
                "family",
            )

            self.assertEqual(created["owner"], "family")
            self.assertTrue(created["shareFamily"])
            self.assertEqual(server.list_event_presets("family")["items"][0]["name"], "당직")

            updated = server.upsert_event_preset({"name": "당직2", "title": "당직2"}, "family", created["id"])
            self.assertEqual(updated["id"], created["id"])
            self.assertEqual(updated["name"], "당직2")

            deleted = server.delete_event_preset(created["id"])
            self.assertTrue(deleted["deleted"])
            self.assertEqual(server.list_event_presets("family")["items"], [])

    def test_recurring_tasks_crud_can_store_disabled_family_rule_without_radicale_write(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temporary:
            server.RECURRING_TASKS_FILE = str(Path(temporary) / "recurring-tasks.json")

            created = server.upsert_recurring_task(
                {
                    "title": "인플루엔자 표본감시 신고",
                    "firstDueDate": "2026-08-03",
                    "dueTime": "16:00",
                    "frequency": "weekly",
                    "enabled": False,
                    "shareFamily": True,
                },
                "family",
            )

            self.assertEqual(created["owner"], "family")
            self.assertEqual(created["adapterProfile"], "family")
            self.assertEqual(created["frequency"], "weekly")
            self.assertEqual(server.list_recurring_tasks("family")["items"][0]["title"], "인플루엔자 표본감시 신고")

            updated = server.upsert_recurring_task({"title": "표본감시", "enabled": False}, "family", created["id"])
            self.assertEqual(updated["id"], created["id"])
            self.assertEqual(updated["title"], "표본감시")

            deleted = server.delete_recurring_task(created["id"])
            self.assertTrue(deleted["deleted"])
            self.assertEqual(server.list_recurring_tasks("family")["items"], [])

    def test_rouny_document_persists_revisioned_family_templates(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temporary:
            server.ROUNY_TEMPLATES_FILE = str(Path(temporary) / "rouny-templates.json")
            templates = [
                {
                    "id": "template-1",
                    "name": "기본",
                    "createdAt": "2026-08-18T00:00:00.000Z",
                    "updatedAt": "2026-08-18T00:00:00.000Z",
                    "items": [
                        {
                            "id": "item-1",
                            "title": "세린샘",
                            "memo": "",
                            "color": "#A7C6FF",
                            "slots": [
                                {
                                    "id": "slot-1",
                                    "dayOfWeek": "2",
                                    "startTime": "19:30",
                                    "endTime": "21:00",
                                }
                            ],
                        }
                    ],
                }
            ]

            saved = server.put_rouny_document({"baseRevision": 0, "templates": templates})
            current = server.rouny_document()

            self.assertEqual(saved["revision"], 1)
            self.assertEqual(current["templates"][0]["name"], "기본")
            self.assertEqual(current["templates"][0]["items"][0]["color"], "#a7c6ff")

    def test_rouny_document_rejects_stale_revision_with_current_copy(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temporary:
            server.ROUNY_TEMPLATES_FILE = str(Path(temporary) / "rouny-templates.json")
            template = {
                "id": "template-1",
                "name": "기본",
                "items": [
                    {
                        "id": "item-1",
                        "title": "수업",
                        "memo": "",
                        "color": "#f4c7df",
                        "slots": [{"id": "slot-1", "dayOfWeek": "1", "startTime": "09:00", "endTime": "09:40"}],
                    }
                ],
            }
            server.put_rouny_document({"baseRevision": 0, "templates": [template]})

            with self.assertRaises(server.RounyConflict) as caught:
                server.put_rouny_document({"baseRevision": 0, "templates": [template]})

            self.assertEqual(caught.exception.document["revision"], 1)

    def test_rouny_validation_rejects_invalid_time_range(self) -> None:
        server = load_server_module()

        with self.assertRaisesRegex(ValueError, "invalid_rouny_time_range"):
            server.validate_rouny_templates(
                [
                    {
                        "id": "template-1",
                        "name": "기본",
                        "items": [
                            {
                                "id": "item-1",
                                "title": "수업",
                                "memo": "",
                                "color": "#f4c7df",
                                "slots": [
                                    {
                                        "id": "slot-1",
                                        "dayOfWeek": "1",
                                        "startTime": "09:00",
                                        "endTime": "09:00",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            )

    def test_public_holidays_wrap_family_holidays_for_portal_contract(self) -> None:
        server = load_server_module()
        server.list_family_holidays = lambda: {
            "ok": True,
            "collection": {"id": "family:calendar"},
            "items": [
                {
                    "uid": "KAOS-HOLIDAY-ABCDEFABCDEFABCDEFABCDEF",
                    "summary": "광복절",
                    "startDate": "2026-08-15",
                    "endDate": "2026-08-15",
                    "categories": [
                        "KAOS-GOOGLE-HOLIDAY",
                        "KAOS-PUBLIC-HOLIDAY",
                        "KAOS-SYSTEM",
                    ],
                }
            ],
        }

        payload = server.list_public_holidays()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["collection"], {"id": "family:calendar"})
        self.assertEqual(payload["items"][0]["title"], "광복절")
        self.assertTrue(payload["items"][0]["publicHoliday"])
        self.assertFalse(payload["sync"]["enabled"])

    def test_set_public_holiday_rewrites_holiday_categories(self) -> None:
        server = load_server_module()
        calls = []
        server.list_family_holidays = lambda: {
            "ok": True,
            "collection": {"id": "family:calendar"},
            "items": [
                {
                    "uid": "KAOS-HOLIDAY-ABCDEFABCDEFABCDEFABCDEF",
                    "summary": "어버이날",
                    "description": "Google Korea Holidays",
                    "startDate": "2026-05-08",
                    "endDate": "2026-05-08",
                    "categories": [
                        "KAOS-GOOGLE-HOLIDAY",
                        "KAOS-OBSERVANCE",
                        "KAOS-SYSTEM",
                    ],
                }
            ],
        }
        server.put_family_holiday = lambda payload: calls.append(payload) or {"ok": True}

        result = server.set_public_holiday("KAOS-HOLIDAY-ABCDEFABCDEFABCDEFABCDEF", True)

        self.assertTrue(result["item"]["publicHoliday"])
        self.assertEqual(calls[0]["title"], "어버이날")
        self.assertIn("KAOS-PUBLIC-HOLIDAY", calls[0]["categories"])
        self.assertNotIn("KAOS-OBSERVANCE", calls[0]["categories"])

    def test_generated_calendar_settings_persist_to_state_file(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temporary:
            server.GENERATED_CALENDAR_FILE = str(Path(temporary) / "generated-calendar.json")

            settings = server.update_generated_calendar_settings(
                {"marketDaysEnabled": False, "claimDayEnabled": True}
            )
            payload = server.generated_calendar_settings_payload()

            self.assertFalse(settings["marketDaysEnabled"])
            self.assertTrue(settings["claimDayEnabled"])
            self.assertEqual(payload["settings"]["marketDaysEnabled"], False)
            self.assertTrue(payload["sync"]["configured"])

    def test_sync_generated_calendar_creates_updates_and_deletes_target_years(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temporary:
            server.GENERATED_CALENDAR_FILE = str(Path(temporary) / "generated-calendar.json")
            server.update_generated_calendar_settings({"marketDaysEnabled": False, "claimDayEnabled": True})
            created = []
            deleted = []

            server.list_public_holidays = lambda: {
                "ok": True,
                "items": [{"startDate": "2026-01-02", "publicHoliday": True}],
            }
            server.list_gdd_generated_events = lambda: {
                "ok": True,
                "items": [
                    {
                        "uid": "KAOS-CLAIM-WEEK-2026-01-02",
                        "summary": "Old Claim",
                        "description": "Generated by KaosGDD Brain",
                        "startDate": "2026-01-02",
                        "endDate": "2026-01-02",
                        "categories": [
                            "KAOS-SYSTEM",
                            "KAOS-GENERATED-CALENDAR",
                            "KAOS-CLAIM-DAY",
                        ],
                    },
                    {
                        "uid": "KAOS-MARKET-2026-01-05",
                        "summary": "Market Day",
                        "description": "Generated by KaosGDD Brain",
                        "startDate": "2026-01-05",
                        "endDate": "2026-01-05",
                        "categories": [
                            "KAOS-SYSTEM",
                            "KAOS-GENERATED-CALENDAR",
                            "KAOS-MARKET-DAY",
                        ],
                    },
                    {
                        "uid": "KAOS-MARKET-2028-01-05",
                        "summary": "Market Day",
                        "description": "Generated by KaosGDD Brain",
                        "startDate": "2028-01-05",
                        "endDate": "2028-01-05",
                        "categories": [
                            "KAOS-SYSTEM",
                            "KAOS-GENERATED-CALENDAR",
                            "KAOS-MARKET-DAY",
                        ],
                    },
                ],
            }
            server.put_gdd_generated_event = lambda payload: created.append(payload) or {"ok": True, "created": False}
            server.delete_gdd_generated_event = lambda payload: deleted.append(payload) or {"ok": True, "deleted": True}

            result = server.sync_generated_calendar(today=server.date(2026, 1, 1))

            self.assertTrue(result["ok"])
            self.assertEqual(result["years"], [2026, 2027])
            self.assertEqual(result["total"], 105)
            self.assertGreaterEqual(result["updated"], 1)
            self.assertTrue(any(item["uid"] == "KAOS-CLAIM-WEEK-2026-01-02" for item in created))
            self.assertTrue(any(item["uid"] == "KAOS-MARKET-2026-01-05" for item in deleted))
            self.assertFalse(any(item["uid"] == "KAOS-MARKET-2028-01-05" for item in deleted))


if __name__ == "__main__":
    unittest.main()
