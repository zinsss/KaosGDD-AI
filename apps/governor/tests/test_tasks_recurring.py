from datetime import UTC, date, datetime, time
from pathlib import Path
import unittest

from kaos_governor.tasks import recurring


class RecurringTaskValidationTests(unittest.TestCase):
    def test_payload_uses_personal_owner_unless_family_scoped(self) -> None:
        payload = {
            "title": "  Medication   review ",
            "firstDueDate": "2026-08-03",
            "dueTime": "10:00",
            "priority": "5",
            "frequency": "weekly",
        }

        self.assertEqual(recurring.validate_payload(payload)["owner"], "zin")
        self.assertEqual(recurring.validate_payload(payload, family_scope=True)["owner"], "family")
        self.assertEqual(recurring.validate_payload({**payload, "shareFamily": True})["owner"], "family")
        self.assertEqual(recurring.validate_payload(payload)["title"], "Medication review")

    def test_due_time_requires_five_minute_step(self) -> None:
        with self.assertRaisesRegex(recurring.RecurringTaskError, "invalid_dueTime_step"):
            recurring.validate_time("10:03")
        self.assertEqual(recurring.validate_time("10:05"), time(10, 5))


class RecurringTaskDateTests(unittest.TestCase):
    def test_monthly_schedule_preserves_original_day(self) -> None:
        anchor = date(2027, 1, 31)
        february = recurring.next_scheduled_date(anchor, "monthly", anchor=anchor)
        march = recurring.next_scheduled_date(february, "monthly", anchor=anchor)

        self.assertEqual(february, date(2027, 2, 28))
        self.assertEqual(march, date(2027, 3, 31))

    def test_yearly_schedule_recovers_after_leap_day(self) -> None:
        anchor = date(2028, 2, 29)
        following = recurring.next_scheduled_date(anchor, "yearly", anchor=anchor)
        recovered = recurring.next_scheduled_date(following, "yearly", anchor=anchor)

        self.assertEqual(following, date(2029, 2, 28))
        self.assertEqual(recovered, date(2030, 2, 28))

    def test_missed_dates_fast_forward_to_current_schedule(self) -> None:
        self.assertEqual(
            recurring.date_on_or_after(date(2026, 7, 1), "weekly", today=date(2026, 8, 3)),
            date(2026, 8, 5),
        )

    def test_occurrence_uid_is_stable_for_definition_and_date(self) -> None:
        item = {"id": "45a6ad4c-bef1-4322"}

        self.assertEqual(
            recurring.occurrence_uid(item, date(2026, 8, 3)),
            "KAOSGDD-REPEAT-45A6AD4CBEF14322-20260803",
        )


class RecurringTaskSynchronizationTests(unittest.TestCase):
    def definition(self, **overrides):
        item = {
            "id": "repeat-1",
            "owner": "zin",
            "collection_id": "zin:tasks",
            "title": "Weekly review",
            "memo": "",
            "first_due_date": date(2026, 8, 3),
            "due_time": time(10, 0),
            "priority": "",
            "frequency": "weekly",
            "active_uid": None,
            "active_collection_id": None,
            "active_due_date": None,
            "next_due_date": date(2026, 8, 3),
        }
        item.update(overrides)
        return item

    def test_new_definition_creates_one_current_occurrence(self) -> None:
        item = self.definition(first_due_date=date(2026, 7, 6), next_due_date=date(2026, 7, 6))

        plan = recurring.plan_synchronization(item, [], today=date(2026, 8, 3))

        self.assertEqual(plan.action, "create")
        self.assertEqual(plan.due_date, date(2026, 8, 3))
        self.assertEqual(plan.uid, "KAOSGDD-REPEAT-REPEAT1-20260803")

    def test_future_definition_waits_for_scheduled_date(self) -> None:
        item = self.definition(next_due_date=date(2026, 8, 10))

        plan = recurring.plan_synchronization(item, [], today=date(2026, 8, 3))

        self.assertEqual(plan.action, "none")
        self.assertIsNone(plan.due_date)


class FakeCalendarAdapter:
    def __init__(self, tasks=None, result=None):
        self.tasks = list(tasks or [])
        self.result = dict(result or {})
        self.created = []
        self.listed_profiles = []

    def list_tasks(self, profile):
        self.listed_profiles.append(profile)
        return list(self.tasks)

    def create_task(self, profile, payload):
        self.created.append((profile, payload))
        return dict(self.result or {"uid": payload["uid"], "collection": payload["collectionId"]})


class RecurringTaskStoreAndServiceTests(unittest.TestCase):
    def definition(self, **overrides) -> recurring.RecurringTaskDefinition:
        values = {
            "definition_id": "repeat-1",
            "owner": "zin",
            "scope": "personal",
            "adapter_profile": "main",
            "collection_id": "zin:tasks",
            "title": "Weekly review",
            "memo": "",
            "first_due_date": date(2026, 8, 3),
            "due_time": time(10, 0),
            "priority": "",
            "frequency": "weekly",
            "next_due_date": date(2026, 8, 3),
        }
        values.update(overrides)
        return recurring.RecurringTaskDefinition(**values)

    def test_store_creates_updates_lists_and_deletes_definitions(self) -> None:
        now = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
        store = recurring.MemoryRecurringTaskStore()
        stored = store.upsert_definition(self.definition(), now=now)
        updated = store.upsert_definition(self.definition(title="Updated"), now=now)

        self.assertEqual(stored.created_at, now)
        self.assertEqual(updated.created_at, now)
        self.assertEqual(store.enabled_definitions()[0].title, "Updated")

        store.delete_definition("repeat-1")
        self.assertEqual(store.enabled_definitions(), [])

    def test_service_creates_current_occurrence_and_records_active_mapping(self) -> None:
        store = recurring.MemoryRecurringTaskStore()
        definition = store.upsert_definition(self.definition(first_due_date=date(2026, 7, 6), next_due_date=date(2026, 7, 6)))
        adapter = FakeCalendarAdapter()
        service = recurring.RecurringTaskService(store, adapter)

        plan = service.synchronize_definition(definition, today=date(2026, 8, 3))
        updated = store.get_definition("repeat-1")

        self.assertEqual(plan.action, "create")
        self.assertEqual(len(adapter.created), 1)
        self.assertEqual(adapter.created[0][1]["dueDate"], "2026-08-03")
        self.assertEqual(updated.active_uid, "KAOSGDD-REPEAT-REPEAT1-20260803")
        self.assertIsNone(updated.next_due_date)

    def test_service_adopts_existing_deterministic_occurrence_without_create(self) -> None:
        store = recurring.MemoryRecurringTaskStore()
        definition = store.upsert_definition(self.definition())
        uid = recurring.occurrence_uid(definition.as_planner_mapping(), date(2026, 8, 3))
        adapter = FakeCalendarAdapter(tasks=[{"uid": uid, "collection": "zin:tasks", "status": "NEEDS-ACTION"}])
        service = recurring.RecurringTaskService(store, adapter)

        plan = service.synchronize_definition(definition, today=date(2026, 8, 3))
        updated = store.get_definition("repeat-1")

        self.assertEqual(plan.action, "adopt")
        self.assertEqual(adapter.created, [])
        self.assertEqual(updated.active_uid, uid)

    def test_service_waits_until_next_schedule_after_completed_active_occurrence(self) -> None:
        now = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
        store = recurring.MemoryRecurringTaskStore()
        definition = store.upsert_definition(
            self.definition(
                active_uid="generated-1",
                active_collection_id="zin:tasks",
                active_due_date=date(2026, 8, 3),
                next_due_date=None,
            ),
            now=now,
        )
        adapter = FakeCalendarAdapter(tasks=[{"uid": "generated-1", "collection": "zin:tasks", "status": "COMPLETED"}])
        service = recurring.RecurringTaskService(store, adapter)

        plan = service.synchronize_definition(definition, today=date(2026, 8, 3), now=now)
        updated = store.get_definition("repeat-1")

        self.assertEqual(plan.action, "none")
        self.assertEqual(adapter.created, [])
        self.assertEqual(updated.last_completed_uid, "generated-1")
        self.assertEqual(updated.next_due_date, date(2026, 8, 10))
        self.assertEqual(updated.active_uid, "")
        self.assertIsNone(updated.active_due_date)

        plan = service.synchronize_definition(updated, today=date(2026, 8, 10), now=now)
        updated = store.get_definition("repeat-1")

        self.assertEqual(plan.action, "create")
        self.assertEqual(adapter.created[0][1]["dueDate"], "2026-08-10")
        self.assertEqual(updated.active_due_date, date(2026, 8, 10))

    def test_run_once_skips_disabled_definitions(self) -> None:
        store = recurring.MemoryRecurringTaskStore()
        store.upsert_definition(self.definition(enabled=False))
        adapter = FakeCalendarAdapter()
        service = recurring.RecurringTaskService(store, adapter)

        self.assertEqual(service.run_once(today=date(2026, 8, 3)), [])
        self.assertEqual(adapter.listed_profiles, [])

    def test_recurring_task_migration_declares_required_table_and_indexes(self) -> None:
        migration_path = next(
            (
                parent / "migrations" / "002_recurring_tasks.sql"
                for parent in Path(__file__).resolve().parents
                if (parent / "migrations" / "002_recurring_tasks.sql").exists()
            ),
            None,
        )
        self.assertIsNotNone(migration_path)
        migration = migration_path.read_text(encoding="utf-8")

        for required in (
            "CREATE TABLE IF NOT EXISTS governor_recurring_task_definitions",
            "governor_recurring_task_definitions_enabled_idx",
            "governor_recurring_task_definitions_owner_idx",
            "governor_recurring_task_definitions_active_uid_idx",
            "Actual task data remains authoritative in Radicale",
        ):
            self.assertIn(required, migration)

    def test_completed_occurrence_waits_for_next_scheduled_date(self) -> None:
        item = self.definition(
            active_uid="generated-1",
            active_collection_id="zin:tasks",
            active_due_date=date(2026, 8, 3),
            next_due_date=None,
        )
        tasks = [{"uid": "generated-1", "collection": "zin:tasks", "status": "COMPLETED"}]

        plan = recurring.plan_synchronization(item, tasks, today=date(2026, 8, 3))

        self.assertTrue(plan.clear_active)
        self.assertTrue(plan.active_completed)
        self.assertEqual(plan.action, "none")
        self.assertIsNone(plan.due_date)
        self.assertEqual(plan.next_due_date, date(2026, 8, 10))

    def test_deleted_occurrence_also_waits_for_next_scheduled_date(self) -> None:
        item = self.definition(
            active_uid="generated-1",
            active_collection_id="zin:tasks",
            active_due_date=date(2026, 8, 3),
            next_due_date=None,
        )

        plan = recurring.plan_synchronization(item, [], today=date(2026, 8, 3))

        self.assertTrue(plan.clear_active)
        self.assertFalse(plan.active_completed)
        self.assertEqual(plan.action, "none")
        self.assertIsNone(plan.due_date)
        self.assertEqual(plan.next_due_date, date(2026, 8, 10))

    def test_cleared_occurrence_creates_when_next_scheduled_date_arrives(self) -> None:
        item = self.definition(next_due_date=date(2026, 8, 10))

        plan = recurring.plan_synchronization(item, [], today=date(2026, 8, 10))

        self.assertEqual(plan.action, "create")
        self.assertEqual(plan.due_date, date(2026, 8, 10))

    def test_active_occurrence_is_not_duplicated(self) -> None:
        item = self.definition(
            active_uid="generated-1",
            active_collection_id="zin:tasks",
            active_due_date=date(2026, 8, 3),
            next_due_date=None,
        )
        tasks = [{"uid": "generated-1", "collection": "zin:tasks", "status": "NEEDS-ACTION"}]

        plan = recurring.plan_synchronization(item, tasks, today=date(2026, 8, 3))

        self.assertEqual(plan.action, "none")

    def test_existing_deterministic_occurrence_is_adopted_after_restart(self) -> None:
        item = self.definition()
        uid = recurring.occurrence_uid(item, date(2026, 8, 3))
        tasks = [{"uid": uid, "collection": "zin:tasks", "status": "NEEDS-ACTION"}]

        plan = recurring.plan_synchronization(item, tasks, today=date(2026, 8, 3))

        self.assertEqual(plan.action, "adopt")
        self.assertEqual(plan.uid, uid)
        self.assertEqual(plan.due_date, date(2026, 8, 3))


if __name__ == "__main__":
    unittest.main()
