from __future__ import annotations

from dataclasses import dataclass
import unittest

from kaos_governor import Actor, GovernorOperations, MemoryDurableGovernorStore
from kaos_governor.memos import (
    MEMO_OPERATION_TYPES,
    MemoMutationCommand,
    MemoMutationError,
    MemoMutationService,
)


@dataclass(frozen=True)
class FakeMemo:
    name: str
    content: str


class FakeMemoAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.result_name = "memos/1"
        self.error: Exception | None = None

    def create(self, content, *, visibility="PRIVATE"):
        if self.error is not None:
            raise self.error
        self.calls.append(("create", content, visibility))
        return FakeMemo(self.result_name, str(content))

    def update(self, name, content):
        if self.error is not None:
            raise self.error
        self.calls.append(("edit", name, content))
        return FakeMemo(self.result_name, str(content))

    def delete(self, name):
        if self.error is not None:
            raise self.error
        self.calls.append(("delete", name))


class MemoMutationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeMemoAdapter()
        self.service = MemoMutationService(self.adapter)

    def test_every_declared_memo_operation_has_a_registered_handler(self) -> None:
        self.assertEqual(self.service.registered_operations, MEMO_OPERATION_TYPES)

    def test_create_routes_to_the_create_handler(self) -> None:
        result = self.service.execute(MemoMutationCommand("create", content="# New memo"))

        self.assertEqual(result.name, "memos/1")
        self.assertEqual(result.content, "# New memo")
        self.assertEqual(self.adapter.calls, [("create", "# New memo", "PRIVATE")])

    def test_edit_routes_to_the_update_handler(self) -> None:
        result = self.service.execute(
            MemoMutationCommand("edit", name="memos/1", content="# Updated memo")
        )

        self.assertEqual(result.name, "memos/1")
        self.assertEqual(result.content, "# Updated memo")
        self.assertEqual(self.adapter.calls, [("edit", "memos/1", "# Updated memo")])

    def test_delete_routes_to_the_delete_handler(self) -> None:
        result = self.service.execute(MemoMutationCommand("delete", name="memos/1"))

        self.assertEqual(result.name, "memos/1")
        self.assertEqual(self.adapter.calls, [("delete", "memos/1")])

    def test_invalid_commands_are_rejected_before_adapter_call(self) -> None:
        invalid = (
            ("unknown operation", {"operation_type": "archive"}, "memo_operation_not_registered"),
            ("missing create content", {"operation_type": "create"}, "memo_content_required"),
            (
                "invalid edit name",
                {"operation_type": "edit", "name": "bad", "content": "body"},
                "memo_name_invalid",
            ),
            ("missing edit content", {"operation_type": "edit", "name": "memos/1"}, "memo_content_required"),
            ("invalid delete name", {"operation_type": "delete", "name": "bad"}, "memo_name_invalid"),
            (
                "oversize content",
                {"operation_type": "create", "content": "x" * 8001},
                "memo_content_too_long",
            ),
        )
        for label, values, code in invalid:
            with self.subTest(label=label):
                with self.assertRaisesRegex(MemoMutationError, code):
                    MemoMutationCommand(**values)
        self.assertEqual(self.adapter.calls, [])

    def test_adapter_name_mismatch_is_rejected(self) -> None:
        self.adapter.result_name = "memos/2"

        with self.assertRaisesRegex(MemoMutationError, "memo_adapter_name_mismatch"):
            self.service.execute(
                MemoMutationCommand("edit", name="memos/1", content="# Updated")
            )

    def test_governed_execution_records_fingerprint_without_content(self) -> None:
        store = MemoryDurableGovernorStore()
        operations = GovernorOperations(store)

        execution = self.service.execute_governed(
            operations,
            MemoMutationCommand("create", content="private body"),
            actor=Actor("user", "200", "personal"),
            idempotency_key="discord-message:700",
        )

        self.assertTrue(execution.created)
        self.assertEqual(execution.operation.status, "completed")
        self.assertEqual(execution.operation.result, {"name": "memos/1"})
        self.assertNotIn("content", execution.operation.parameters)
        self.assertEqual(execution.operation.parameters["contentFingerprint"]["bytes"], 12)
        self.assertEqual(
            [record.outcome for record in store.audit_records(execution.operation.operation_id)],
            ["accepted", "completed"],
        )

    def test_governed_execution_replay_does_not_repeat_adapter_write(self) -> None:
        store = MemoryDurableGovernorStore()
        operations = GovernorOperations(store)
        actor = Actor("user", "200", "personal")
        command = MemoMutationCommand("delete", name="memos/1", content="private body")

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
        self.assertEqual(replay.mutation.name, "memos/1")
        self.assertEqual(replay.mutation.content, "private body")
        self.assertEqual(self.adapter.calls, [("delete", "memos/1")])

    def test_governed_adapter_failure_marks_operation_failed(self) -> None:
        store = MemoryDurableGovernorStore()
        operations = GovernorOperations(store)
        self.adapter.error = RuntimeError("offline")

        with self.assertRaisesRegex(RuntimeError, "offline"):
            self.service.execute_governed(
                operations,
                MemoMutationCommand("create", content="body"),
                actor=Actor("user", "200", "personal"),
                idempotency_key="discord-message:701",
            )

        audit = store.audit_records()
        operation = store.get_operation(audit[0].operation_id)
        assert operation is not None
        self.assertEqual(operation.status, "failed")
        self.assertEqual(operation.error_code, "memo_adapter_error")
        self.assertEqual([record.outcome for record in audit], ["accepted", "failed"])


if __name__ == "__main__":
    unittest.main()
