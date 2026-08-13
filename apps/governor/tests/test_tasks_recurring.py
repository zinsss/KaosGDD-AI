from datetime import date, time
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

    def test_completed_occurrence_advances_fixed_schedule(self) -> None:
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
        self.assertEqual(plan.action, "create")
        self.assertEqual(plan.due_date, date(2026, 8, 10))

    def test_deleted_occurrence_also_advances(self) -> None:
        item = self.definition(
            active_uid="generated-1",
            active_collection_id="zin:tasks",
            active_due_date=date(2026, 8, 3),
            next_due_date=None,
        )

        plan = recurring.plan_synchronization(item, [], today=date(2026, 8, 3))

        self.assertTrue(plan.clear_active)
        self.assertFalse(plan.active_completed)
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
