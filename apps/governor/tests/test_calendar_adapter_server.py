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

    def test_updated_vtodo_preserves_existing_uid_case_for_ios_clients(self) -> None:
        server = load_server_module()
        existing = {
            "UID": "ios-Mixed-Case-Task",
            "CREATED": "20260818T000000Z",
            "SEQUENCE": "4",
            "_raw_properties": ["UID:ios-Mixed-Case-Task"],
        }

        uid, body = server.build_vtodo(
            {"uid": "ios-Mixed-Case-Task", "title": "Check", "status": "COMPLETED"},
            existing,
        )

        self.assertEqual(uid, "ios-Mixed-Case-Task")
        self.assertIn("UID:ios-Mixed-Case-Task", body)
        self.assertNotIn("UID:IOS-MIXED-CASE-TASK", body)

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

    def test_create_task_rejects_future_recurring_occurrence_direct_writes(self) -> None:
        server = load_server_module()
        original_configured = server.configured
        original_collections = server.collections_for_profile
        original_select = server.select_collection
        original_radicale = server.radicale_request
        try:
            server.configured = lambda profile: True
            server.collections_for_profile = lambda profile: [{"id": "zin:tasks", "href": "http://radicale/tasks/", "components": ["VTODO"]}]
            server.select_collection = lambda collections, collection_id, component: collections[0]
            server.radicale_request = lambda *_args, **_kwargs: self.fail("future recurring write reached Radicale")

            with self.assertRaisesRegex(ValueError, "recurring_occurrence_not_due"):
                server.create_task(
                    {
                        "uid": "KAOSGDD-REPEAT-A50D23EBEBBE4E5AA9FDDEEFF54A528C-20990101",
                        "collectionId": "zin:tasks",
                        "title": "인플루엔자 표본감시 신고",
                        "dueDate": "2099-01-01",
                        "dueTime": "16:00",
                    }
                )
        finally:
            server.configured = original_configured
            server.collections_for_profile = original_collections
            server.select_collection = original_select
            server.radicale_request = original_radicale

    def test_create_task_rejects_recurring_occurrence_uid_due_mismatch(self) -> None:
        server = load_server_module()

        with self.assertRaisesRegex(ValueError, "recurring_occurrence_uid_due_mismatch"):
            server.reject_future_recurring_occurrence(
                {
                    "uid": "KAOSGDD-REPEAT-A50D23EBEBBE4E5AA9FDDEEFF54A528C-20990101",
                    "dueDate": "2099-01-08",
                }
            )

    def test_recurring_task_waits_for_future_scheduled_date(self) -> None:
        server = load_server_module()
        created = []
        original_collections = server.collections_for_profile
        original_select = server.select_collection
        original_create = server.create_task
        try:
            server.collections_for_profile = lambda profile: [{"id": "zin:tasks", "components": ["VTODO"]}]
            server.select_collection = lambda collections, collection_id, component: collections[0]
            server.create_task = lambda payload, profile: created.append((profile, payload)) or {"ok": True}
            item = server.normalize_recurring_task(
                {
                    "id": "repeat-1",
                    "owner": "zin",
                    "collectionId": "zin:tasks",
                    "title": "인플루엔자 표본감시 신고",
                    "firstDueDate": "2026-08-03",
                    "dueTime": "16:00",
                    "frequency": "weekly",
                }
            )

            result = server.ensure_recurring_occurrence(item, today=server.date(2026, 8, 18), tasks=[])

            self.assertEqual(created, [])
            self.assertEqual(result["nextDueDate"], "2026-08-24")
            self.assertEqual(result["activeUid"], "")
        finally:
            server.collections_for_profile = original_collections
            server.select_collection = original_select
            server.create_task = original_create

    def test_recurring_task_creates_when_scheduled_date_arrives(self) -> None:
        server = load_server_module()
        created = []
        original_collections = server.collections_for_profile
        original_select = server.select_collection
        original_create = server.create_task
        try:
            server.collections_for_profile = lambda profile: [{"id": "zin:tasks", "components": ["VTODO"]}]
            server.select_collection = lambda collections, collection_id, component: collections[0]
            server.create_task = lambda payload, profile: created.append((profile, payload)) or {"ok": True}
            item = server.normalize_recurring_task(
                {
                    "id": "repeat-1",
                    "owner": "zin",
                    "collectionId": "zin:tasks",
                    "title": "인플루엔자 표본감시 신고",
                    "firstDueDate": "2026-08-03",
                    "dueTime": "16:00",
                    "frequency": "weekly",
                    "nextDueDate": "2026-08-24",
                }
            )

            result = server.ensure_recurring_occurrence(item, today=server.date(2026, 8, 24), tasks=[])

            self.assertEqual(created[0][1]["dueDate"], "2026-08-24")
            self.assertEqual(result["activeDueDate"], "2026-08-24")
            self.assertEqual(result["nextDueDate"], "")
        finally:
            server.collections_for_profile = original_collections
            server.select_collection = original_select
            server.create_task = original_create

    def test_recurring_task_repairs_missing_active_from_latest_completed_occurrence(self) -> None:
        server = load_server_module()
        created = []
        original_collections = server.collections_for_profile
        original_select = server.select_collection
        original_create = server.create_task
        try:
            server.collections_for_profile = lambda profile: [{"id": "zin:tasks", "components": ["VTODO"]}]
            server.select_collection = lambda collections, collection_id, component: collections[0]
            server.create_task = lambda payload, profile: created.append((profile, payload)) or {"ok": True}
            item = server.normalize_recurring_task(
                {
                    "id": "a50d23eb-ebbe-4e5a-a9fd-deeff54a528c",
                    "owner": "zin",
                    "collectionId": "zin:tasks",
                    "title": "인플루엔자 표본감시 신고",
                    "firstDueDate": "2026-08-03",
                    "dueTime": "16:00",
                    "frequency": "weekly",
                    "activeUid": "KAOSGDD-REPEAT-A50D23EBEBBE4E5AA9FDDEEFF54A528C-20260831",
                    "activeCollectionId": "zin:tasks",
                    "activeDueDate": "2026-08-31",
                }
            )
            tasks = [
                {
                    "uid": "KAOSGDD-REPEAT-A50D23EBEBBE4E5AA9FDDEEFF54A528C-20260817",
                    "collection": "zin:tasks",
                    "status": "COMPLETED",
                    "completed": "2026-08-18T13:50:33",
                }
            ]

            result = server.ensure_recurring_occurrence(item, today=server.date(2026, 8, 18), tasks=tasks)

            self.assertEqual(created, [])
            self.assertEqual(result["activeUid"], "")
            self.assertEqual(result["nextDueDate"], "2026-08-24")
            self.assertEqual(result["lastCompletedUid"], tasks[0]["uid"])
        finally:
            server.collections_for_profile = original_collections
            server.select_collection = original_select
            server.create_task = original_create

    def test_sync_recurring_tasks_updates_profile_rules_without_creating_future_tasks(self) -> None:
        server = load_server_module()
        with tempfile.TemporaryDirectory() as temporary:
            server.RECURRING_TASKS_FILE = str(Path(temporary) / "recurring-tasks.json")
            created = []
            original_collections = server.collections_for_profile
            original_select = server.select_collection
            original_create = server.create_task
            original_delete = server.delete_task
            original_bootstrap = server.bootstrap_payload
            try:
                server.collections_for_profile = lambda profile: [{"id": "zin:tasks", "components": ["VTODO"]}]
                server.select_collection = lambda collections, collection_id, component: collections[0]
                server.create_task = lambda payload, profile: created.append((profile, payload)) or {"ok": True}
                deleted = []
                server.delete_task = lambda payload, profile: deleted.append((profile, payload)) or {"ok": True}
                future_uid = server.recurring_occurrence_uid({"id": "repeat-1"}, server.date(2099, 1, 1))
                server.bootstrap_payload = lambda profile: {
                    "tasks": [
                        {
                            "uid": future_uid,
                            "collection": "zin:tasks",
                            "status": "NEEDS-ACTION",
                        }
                    ]
                }
                server.save_recurring_task_store(
                    [
                        server.normalize_recurring_task(
                            {
                                "id": "repeat-1",
                                "owner": "zin",
                                "collectionId": "zin:tasks",
                                "title": "미래 반복 할 일",
                                "firstDueDate": "2099-01-01",
                                "dueTime": "10:00",
                                "frequency": "weekly",
                            }
                        )
                    ]
                )

                result = server.sync_recurring_tasks("main")

                self.assertTrue(result["ok"])
                self.assertTrue(result["changed"])
                self.assertEqual(created, [])
                self.assertEqual(deleted, [("main", {"uid": future_uid, "collectionId": "zin:tasks"})])
                self.assertEqual(result["items"][0]["nextDueDate"], "2099-01-01")
                self.assertEqual(server.recurring_task_store()[0]["nextDueDate"], "2099-01-01")
            finally:
                server.collections_for_profile = original_collections
                server.select_collection = original_select
                server.create_task = original_create
                server.delete_task = original_delete
                server.bootstrap_payload = original_bootstrap

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
