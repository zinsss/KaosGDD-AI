from __future__ import annotations

import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
