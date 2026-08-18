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


if __name__ == "__main__":
    unittest.main()
