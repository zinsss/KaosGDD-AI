from __future__ import annotations

from datetime import date, time
import unittest
from unittest.mock import patch

from kaos_governor import api
from kaos_governor.tasks import RecurringTaskDefinition


class FakeCalendarAdapter:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args

    def vtodo_collection_id(self, profile: str, preferred: str = "") -> str:
        return preferred or f"{profile}:tasks"


class RecurringTaskApiTests(unittest.TestCase):
    def test_family_request_becomes_family_owned_definition(self) -> None:
        with patch.object(api, "CalendarAdapterClient", FakeCalendarAdapter):
            definition = api.recurring_definition_from_request(
                {
                    "title": "School form",
                    "firstDueDate": "2026-08-24",
                    "dueTime": "10:00",
                    "priority": "",
                    "frequency": "weekly",
                },
                "family",
            )

        self.assertEqual(definition.owner, "family")
        self.assertEqual(definition.scope, "family")
        self.assertEqual(definition.adapter_profile, "family")
        self.assertEqual(definition.collection_id, "family:tasks")
        self.assertEqual(definition.creation_policy, "on_schedule")
        self.assertEqual(definition.next_due_date, date(2026, 8, 24))

    def test_payload_uses_existing_portal_contract(self) -> None:
        payload = api.recurring_task_payload(
            RecurringTaskDefinition(
                definition_id="repeat-1",
                owner="zin",
                scope="personal",
                adapter_profile="main",
                collection_id="zin:tasks",
                title="Weekly report",
                memo="memo",
                first_due_date=date(2026, 8, 3),
                due_time=time(16, 0),
                priority="5",
                frequency="weekly",
                active_uid="task-1",
                active_collection_id="zin:tasks",
                active_due_date=date(2026, 8, 3),
            )
        )

        self.assertEqual(payload["id"], "repeat-1")
        self.assertEqual(payload["collectionId"], "zin:tasks")
        self.assertEqual(payload["firstDueDate"], "2026-08-03")
        self.assertEqual(payload["dueTime"], "16:00")
        self.assertEqual(payload["activeUid"], "task-1")
        self.assertEqual(payload["activeDueDate"], "2026-08-03")
        self.assertFalse(payload["shareFamily"])


if __name__ == "__main__":
    unittest.main()
