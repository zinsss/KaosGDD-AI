from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from kaos_governor import (
    Actor,
    DurableGovernorError,
    GovernorOperations,
    MemoryDurableGovernorStore,
    OperationRequest,
)


class GovernorOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
        self.actor = Actor("user", "discord:123", "personal")
        self.store = MemoryDurableGovernorStore()
        self.operations = GovernorOperations(self.store)

    def request(self, *, requires_confirmation: bool = True) -> OperationRequest:
        return OperationRequest(
            actor=self.actor,
            idempotency_key="request-1",
            tool_name="calendar.tasks",
            operation_type="complete",
            parameters={"profile": "main", "uid": "task-1"},
            requires_confirmation=requires_confirmation,
        )

    def propose(self, **kwargs):
        return self.operations.propose(
            self.request(),
            pending_kind="task.complete",
            pending_payload={"profile": "main", "uid": "task-1"},
            **kwargs,
        )

    def test_confirmation_lifecycle_is_owned_by_governor_boundary(self) -> None:
        submission = self.propose(now=self.now)

        self.assertTrue(submission.created)
        self.assertEqual(submission.operation.status, "requires_confirmation")
        self.assertEqual(submission.confirmation.expires_at, self.now + timedelta(minutes=10))
        pending = self.operations.get_pending_payload(submission.operation.operation_id)
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.payload_kind, "task.complete")
        self.assertEqual(pending.payload, {"profile": "main", "uid": "task-1"})

        approved = self.operations.approve(
            submission.confirmation.confirmation_id,
            actor=self.actor,
            now=self.now + timedelta(minutes=1),
        )
        self.assertEqual(approved.operation.status, "confirmed")
        self.assertEqual(approved.confirmation.status, "approved")

        completed = self.operations.complete(
            submission.operation.operation_id,
            result={"uid": "task-1"},
            now=self.now + timedelta(minutes=2),
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result, {"uid": "task-1"})
        self.assertIsNone(self.operations.get_pending_payload(submission.operation.operation_id))
        self.assertEqual(
            [record.outcome for record in self.store.audit_records(submission.operation.operation_id)],
            ["requires_confirmation", "requires_confirmation", "approved", "completed"],
        )

    def test_non_confirming_submission_preserves_idempotency(self) -> None:
        first = self.operations.submit(self.request(requires_confirmation=False), now=self.now)
        second = self.operations.submit(
            self.request(requires_confirmation=False),
            now=self.now + timedelta(seconds=1),
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.operation.operation_id, first.operation.operation_id)
        self.assertIsNone(first.confirmation)
        self.assertIsNone(second.confirmation)

    def test_duplicate_proposal_reuses_the_same_pending_confirmation(self) -> None:
        first = self.propose(now=self.now)
        second = self.propose(now=self.now + timedelta(seconds=1))

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.operation.operation_id, first.operation.operation_id)
        self.assertEqual(
            second.confirmation.confirmation_id,
            first.confirmation.confirmation_id,
        )

    def test_completed_proposal_cannot_be_reopened_by_idempotency_replay(self) -> None:
        first = self.propose(now=self.now)
        self.operations.approve(
            first.confirmation.confirmation_id,
            actor=self.actor,
            now=self.now + timedelta(minutes=1),
        )
        self.operations.complete(
            first.operation.operation_id,
            result={"uid": "task-1"},
            now=self.now + timedelta(minutes=2),
        )

        with self.assertRaisesRegex(DurableGovernorError, "operation_not_pending"):
            self.propose(now=self.now + timedelta(minutes=3))

    def test_approval_rejects_a_different_actor(self) -> None:
        submission = self.propose(now=self.now)

        with self.assertRaisesRegex(DurableGovernorError, "confirmation_actor_mismatch"):
            self.operations.approve(
                submission.confirmation.confirmation_id,
                actor=Actor("user", "discord:456", "personal"),
                now=self.now + timedelta(minutes=1),
            )

    def test_custom_confirmation_ttl_is_applied(self) -> None:
        submission = self.propose(
            confirmation_ttl=timedelta(seconds=30),
            now=self.now,
        )

        self.assertEqual(submission.confirmation.expires_at, self.now + timedelta(seconds=30))

    def test_invalid_default_confirmation_ttl_is_rejected(self) -> None:
        with self.assertRaisesRegex(DurableGovernorError, "confirmation_ttl_invalid"):
            GovernorOperations(self.store, confirmation_ttl=timedelta())


if __name__ == "__main__":
    unittest.main()
