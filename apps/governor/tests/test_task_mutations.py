from __future__ import annotations

import unittest

from kaos_governor import Actor, GovernorOperations, MemoryDurableGovernorStore
from kaos_governor.tasks import (
    TASK_OPERATION_TYPES,
    TaskMutationCommand,
    TaskMutationError,
    TaskMutationService,
)


class FakeTaskAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.result_uid = "TASK-1"
        self.error: Exception | None = None

    def create_task(self, profile, payload):
        if self.error is not None:
            raise self.error
        self.calls.append(("create", profile, dict(payload)))
        return {"uid": self.result_uid}

    def update_task(self, profile, payload):
        if self.error is not None:
            raise self.error
        self.calls.append(("update", profile, dict(payload)))
        return {"uid": self.result_uid}

    def delete_task(self, profile, uid, collection_id):
        if self.error is not None:
            raise self.error
        self.calls.append(("delete", profile, uid, collection_id))
        return {"uid": self.result_uid}


class TaskMutationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeTaskAdapter()
        self.service = TaskMutationService(self.adapter)

    def test_every_declared_task_operation_has_a_registered_handler(self) -> None:
        self.assertEqual(self.service.registered_operations, TASK_OPERATION_TYPES)

    def test_create_routes_to_the_create_handler(self) -> None:
        result = self.service.execute(
            TaskMutationCommand(
                operation_type="create",
                profile="main",
                payload={"title": "Call school", "memo": "Bring form"},
            )
        )

        self.assertEqual(result.uid, "TASK-1")
        self.assertEqual(
            self.adapter.calls,
            [("create", "main", {"title": "Call school", "memo": "Bring form"})],
        )

    def test_update_operations_route_to_the_update_handler(self) -> None:
        for operation_type in ("update_due", "edit", "complete", "reopen"):
            with self.subTest(operation_type=operation_type):
                self.adapter.calls.clear()
                result = self.service.execute(
                    TaskMutationCommand(
                        operation_type=operation_type,
                        profile="family",
                        uid="TASK-1",
                        collection_id="family:tasks",
                        payload={
                            "uid": "TASK-1",
                            "collectionId": "family:tasks",
                            "title": "Task",
                        },
                    )
                )
                self.assertEqual(result.uid, "TASK-1")
                self.assertEqual(self.adapter.calls[0][0:2], ("update", "family"))

    def test_delete_routes_to_the_delete_handler(self) -> None:
        result = self.service.execute(
            TaskMutationCommand(
                operation_type="delete",
                profile="main",
                uid="TASK-1",
                collection_id="zin:tasks",
                payload={},
            )
        )

        self.assertEqual(result.uid, "TASK-1")
        self.assertEqual(self.adapter.calls, [("delete", "main", "TASK-1", "zin:tasks")])

    def test_unknown_operation_is_rejected_before_adapter_call(self) -> None:
        with self.assertRaisesRegex(TaskMutationError, "task_operation_not_registered"):
            TaskMutationCommand(operation_type="archive", profile="main", payload={})
        self.assertEqual(self.adapter.calls, [])

    def test_update_rejects_uid_mismatch_before_adapter_call(self) -> None:
        with self.assertRaisesRegex(TaskMutationError, "task_uid_mismatch"):
            TaskMutationCommand(
                operation_type="complete",
                profile="main",
                uid="TASK-1",
                payload={"uid": "TASK-2"},
            )
        self.assertEqual(self.adapter.calls, [])

    def test_supplies_schedule_is_rejected_at_domain_boundary(self) -> None:
        with self.assertRaisesRegex(TaskMutationError, "supplies_schedule_not_allowed"):
            TaskMutationCommand(
                operation_type="create",
                profile="supplies",
                payload={"title": "Soap", "dueDate": "2026-09-01"},
            )
        self.assertEqual(self.adapter.calls, [])

    def test_adapter_uid_mismatch_is_rejected(self) -> None:
        self.adapter.result_uid = "TASK-2"
        with self.assertRaisesRegex(TaskMutationError, "task_adapter_uid_mismatch"):
            self.service.execute(
                TaskMutationCommand(
                    operation_type="edit",
                    profile="main",
                    uid="TASK-1",
                    payload={"uid": "TASK-1", "title": "Edited"},
                )
            )

    def test_governed_execution_records_sanitized_operation_and_audit(self) -> None:
        store = MemoryDurableGovernorStore()
        operations = GovernorOperations(store)
        command = TaskMutationCommand(
            operation_type="create",
            profile="main",
            payload={"title": "Call school", "memo": "private body"},
        )

        execution = self.service.execute_governed(
            operations,
            command,
            actor=Actor("user", "200", "personal"),
            idempotency_key="discord-message:700",
        )

        self.assertTrue(execution.created)
        self.assertEqual(execution.operation.status, "completed")
        self.assertEqual(execution.operation.result, {"uid": "TASK-1"})
        self.assertEqual(execution.operation.actor, Actor("user", "200", "personal"))
        self.assertEqual(execution.operation.idempotency_key, "discord-message:700")
        self.assertNotIn("memo", execution.operation.parameters)
        self.assertEqual(execution.operation.parameters["memoFingerprint"]["bytes"], 12)
        self.assertEqual(
            [record.outcome for record in store.audit_records(execution.operation.operation_id)],
            ["accepted", "completed"],
        )

    def test_governed_execution_replay_does_not_repeat_adapter_write(self) -> None:
        store = MemoryDurableGovernorStore()
        operations = GovernorOperations(store)
        command = TaskMutationCommand(
            operation_type="complete",
            profile="main",
            uid="TASK-1",
            collection_id="zin:tasks",
            payload={
                "uid": "TASK-1",
                "collectionId": "zin:tasks",
                "title": "Call school",
                "status": "COMPLETED",
            },
        )
        actor = Actor("user", "200", "personal")

        first = self.service.execute_governed(
            operations,
            command,
            actor=actor,
            idempotency_key="discord-interaction:900",
        )
        replay = self.service.execute_governed(
            operations,
            command,
            actor=actor,
            idempotency_key="discord-interaction:900",
        )

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(replay.mutation.uid, "TASK-1")
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(
            [record.outcome for record in store.audit_records(first.operation.operation_id)],
            ["accepted", "completed"],
        )

    def test_governed_adapter_failure_marks_operation_failed(self) -> None:
        store = MemoryDurableGovernorStore()
        operations = GovernorOperations(store)
        self.adapter.error = RuntimeError("offline")
        command = TaskMutationCommand(
            operation_type="create",
            profile="main",
            payload={"title": "Call school"},
        )

        with self.assertRaisesRegex(RuntimeError, "offline"):
            self.service.execute_governed(
                operations,
                command,
                actor=Actor("user", "200", "personal"),
                idempotency_key="discord-message:701",
            )

        audit = store.audit_records()
        operation = store.get_operation(audit[0].operation_id)
        assert operation is not None
        self.assertEqual(operation.status, "failed")
        self.assertEqual(operation.error_code, "task_adapter_error")
        self.assertEqual([record.outcome for record in audit], ["accepted", "failed"])


if __name__ == "__main__":
    unittest.main()
