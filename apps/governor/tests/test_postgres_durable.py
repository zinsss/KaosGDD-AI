from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import threading
import unittest
import uuid

from psycopg import sql

from kaos_governor.database import apply_migrations, connect, database_status
from kaos_governor.durable import Actor, DurableGovernorError, OperationRequest
from kaos_governor.memos import MemoMutationCommand, MemoMutationService
from kaos_governor.operations import GovernorOperations
from kaos_governor.postgres_durable import PostgresDurableGovernorStore
from kaos_governor.tasks import TaskMutationCommand, TaskMutationService


NOW = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)


class FakeTaskAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def create_task(self, profile, payload):
        self.calls.append(("create", profile, dict(payload)))
        return {"uid": "TASK-POSTGRES-1"}

    def update_task(self, profile, payload):
        self.calls.append(("update", profile, dict(payload)))
        return {"uid": str(payload.get("uid") or "")}

    def delete_task(self, profile, uid, collection_id):
        self.calls.append(("delete", profile, {"uid": uid, "collectionId": collection_id}))
        return {"uid": uid}


class FakeMemoRecord:
    def __init__(self, name: str, content: str) -> None:
        self.name = name
        self.content = content


class FakeMemoAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def create(self, content, *, visibility="PRIVATE"):
        self.calls.append(("create", str(content), visibility))
        return FakeMemoRecord("memos/postgres-1", str(content))

    def update(self, name, content):
        self.calls.append(("edit", str(name), str(content)))
        return FakeMemoRecord(str(name), str(content))

    def delete(self, name):
        self.calls.append(("delete", str(name)))


def _migration_directory() -> Path:
    path = next(
        (
            parent / "migrations"
            for parent in Path(__file__).resolve().parents
            if (parent / "migrations" / "001_governor_foundation.sql").exists()
        ),
        None,
    )
    if path is None:
        raise RuntimeError("governor migrations not found")
    return path


@unittest.skipUnless(
    os.environ.get("GOVERNOR_TEST_POSTGRES", "").strip().lower() in {"1", "true", "yes", "on"},
    "set GOVERNOR_TEST_POSTGRES=true to run PostgreSQL integration tests",
)
class PostgresDurableGovernorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.migrations = _migration_directory()
        apply_migrations(cls.migrations)

    def setUp(self) -> None:
        with connect() as connection:
            connection.execute(
                """
                TRUNCATE governor_operation_payloads,
                         governor_confirmations,
                         governor_audit_records,
                         governor_operations
                """
            )
        self.actor = Actor("user", "discord:postgres-test", "personal")

    def request(self, idempotency_key: str = "postgres-request-1", **parameters) -> OperationRequest:
        return OperationRequest(
            actor=self.actor,
            idempotency_key=idempotency_key,
            tool_name="calendar.tasks",
            operation_type="complete",
            parameters=parameters or {"profile": "main", "uid": "task-1"},
            requires_confirmation=True,
        )

    def propose(self, store: PostgresDurableGovernorStore, **kwargs):
        return GovernorOperations(store).propose(
            self.request(),
            pending_kind="task.complete",
            pending_payload={"profile": "main", "uid": "task-1"},
            now=NOW,
            **kwargs,
        )

    def test_fresh_database_is_at_migration_005_with_payload_contract(self) -> None:
        status = database_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["migration"], "005")

        with connect() as connection:
            parameters_type = connection.execute(
                """
                SELECT data_type
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'governor_operations'
                   AND column_name = 'parameters'
                """
            ).fetchone()
            payload_table = connection.execute(
                "SELECT to_regclass(current_schema() || '.governor_operation_payloads')"
            ).fetchone()

        self.assertEqual(parameters_type, ("jsonb",))
        self.assertIsNotNone(payload_table[0])

    def test_migration_005_upgrades_a_populated_004_schema(self) -> None:
        schema_name = f"governor_upgrade_{uuid.uuid4().hex}"
        migration_files = sorted(self.migrations.glob("00[1-4]_*.sql"))
        migration_005 = self.migrations / "005_durable_operation_payloads.sql"

        with connect() as connection:
            try:
                connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
                connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
                for path in migration_files:
                    connection.execute(path.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO governor_operations (
                        operation_id, idempotency_key, actor_type, actor_id, scope,
                        tool_name, operation_type, request_hash, status
                    )
                    VALUES (
                        'op_existing', 'existing', 'user', 'discord:existing', 'personal',
                        'calendar.tasks', 'complete', %s, 'requires_confirmation'
                    )
                    """,
                    ("a" * 64,),
                )
                connection.execute(migration_005.read_text(encoding="utf-8"))
                row = connection.execute(
                    "SELECT parameters FROM governor_operations WHERE operation_id = 'op_existing'"
                ).fetchone()
                payload_table = connection.execute(
                    "SELECT to_regclass(current_schema() || '.governor_operation_payloads')"
                ).fetchone()
                self.assertEqual(row, ({},))
                self.assertIsNotNone(payload_table[0])
            finally:
                connection.execute("SET search_path TO public")
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
                )

    def test_proposal_survives_new_store_instance_and_terminal_cleanup(self) -> None:
        first_store = PostgresDurableGovernorStore()
        proposal = self.propose(first_store)

        self.assertEqual(proposal.operation.parameters, {"profile": "main", "uid": "task-1"})
        persisted = first_store.get_pending_payload(proposal.operation.operation_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.payload_kind, "task.complete")

        restarted_operations = GovernorOperations(PostgresDurableGovernorStore())
        approved = restarted_operations.approve(
            proposal.confirmation.confirmation_id,
            actor=self.actor,
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(approved.operation.status, "confirmed")
        self.assertIsNotNone(restarted_operations.get_pending_payload(proposal.operation.operation_id))

        completed = restarted_operations.complete(
            proposal.operation.operation_id,
            result={"uid": "task-1"},
            now=NOW + timedelta(minutes=2),
        )
        self.assertEqual(completed.status, "completed")
        self.assertIsNone(restarted_operations.get_pending_payload(proposal.operation.operation_id))

    def test_idempotency_conflict_and_audit_survive_new_store_instance(self) -> None:
        store = PostgresDurableGovernorStore()
        operation, created = store.start_operation(self.request(), now=NOW)
        self.assertTrue(created)

        conflicting = self.request(profile="family", uid="task-2")
        with self.assertRaisesRegex(DurableGovernorError, "idempotency_key_conflict"):
            PostgresDurableGovernorStore().start_operation(
                conflicting,
                now=NOW + timedelta(seconds=1),
            )

        audits = PostgresDurableGovernorStore().audit_records(operation.operation_id)
        self.assertEqual([record.outcome for record in audits], ["requires_confirmation", "rejected"])
        self.assertEqual(audits[-1].reason, "idempotency_key_reused_with_different_request")

    def test_duplicate_proposal_reuses_pending_confirmation_across_store_instances(self) -> None:
        first = self.propose(PostgresDurableGovernorStore())
        second = self.propose(PostgresDurableGovernorStore())

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.operation.operation_id, first.operation.operation_id)
        self.assertEqual(
            second.confirmation.confirmation_id,
            first.confirmation.confirmation_id,
        )

    def test_expired_confirmation_clears_payload_and_marks_operation(self) -> None:
        store = PostgresDurableGovernorStore()
        proposal = self.propose(store, confirmation_ttl=timedelta(seconds=30))

        with self.assertRaisesRegex(DurableGovernorError, "confirmation_expired"):
            GovernorOperations(PostgresDurableGovernorStore()).approve(
                proposal.confirmation.confirmation_id,
                actor=self.actor,
                now=NOW + timedelta(seconds=30),
            )

        restarted = PostgresDurableGovernorStore()
        self.assertEqual(restarted.get_operation(proposal.operation.operation_id).status, "expired")
        self.assertIsNone(restarted.get_pending_payload(proposal.operation.operation_id))

    def test_stale_cleanup_removes_unapproved_payload_without_an_approval_request(self) -> None:
        store = PostgresDurableGovernorStore()
        proposal = self.propose(store, confirmation_ttl=timedelta(seconds=30))

        deleted = PostgresDurableGovernorStore().expire_stale_proposals(
            now=NOW + timedelta(seconds=30)
        )

        restarted = PostgresDurableGovernorStore()
        self.assertEqual(deleted, 1)
        self.assertEqual(restarted.get_operation(proposal.operation.operation_id).status, "expired")
        self.assertEqual(
            restarted.get_confirmation(proposal.confirmation.confirmation_id).status,
            "expired",
        )
        self.assertIsNone(restarted.get_pending_payload(proposal.operation.operation_id))

    def test_interrupted_confirmed_execution_is_failed_and_cleaned_after_grace(self) -> None:
        operations = GovernorOperations(PostgresDurableGovernorStore())
        proposal = self.propose(PostgresDurableGovernorStore())
        operations.approve(
            proposal.confirmation.confirmation_id,
            actor=self.actor,
            now=NOW + timedelta(minutes=1),
        )

        deleted = PostgresDurableGovernorStore().expire_stale_proposals(
            now=NOW + timedelta(hours=1, minutes=10)
        )

        restarted = PostgresDurableGovernorStore()
        operation = restarted.get_operation(proposal.operation.operation_id)
        self.assertEqual(deleted, 1)
        self.assertEqual(operation.status, "failed")
        self.assertEqual(operation.error_code, "execution_interrupted")
        self.assertIsNone(restarted.get_pending_payload(proposal.operation.operation_id))

    def test_concurrent_approval_of_one_confirmation_is_single_use(self) -> None:
        proposal = self.propose(PostgresDurableGovernorStore())
        barrier = threading.Barrier(2)

        def approve_once() -> str:
            store = PostgresDurableGovernorStore()
            barrier.wait(timeout=5)
            try:
                store.approve_confirmation(
                    proposal.confirmation.confirmation_id,
                    actor=self.actor,
                    normalized_operation_hash=proposal.operation.request_hash,
                    now=NOW + timedelta(minutes=1),
                )
            except DurableGovernorError as exc:
                return str(exc)
            return "approved"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = sorted(executor.map(lambda _index: approve_once(), range(2)))

        self.assertEqual(results, ["approved", "confirmation_not_pending"])
        audits = PostgresDurableGovernorStore().audit_records(proposal.operation.operation_id)
        self.assertEqual(sum(record.outcome == "approved" for record in audits), 1)

    def test_governed_task_execution_is_durable_and_idempotent(self) -> None:
        adapter = FakeTaskAdapter()
        service = TaskMutationService(adapter)
        command = TaskMutationCommand(
            operation_type="create",
            profile="main",
            payload={"title": "PostgreSQL task", "memo": "private body"},
        )

        first = service.execute_governed(
            GovernorOperations(PostgresDurableGovernorStore()),
            command,
            actor=self.actor,
            idempotency_key="discord-message:postgres-task",
        )
        replay = service.execute_governed(
            GovernorOperations(PostgresDurableGovernorStore()),
            command,
            actor=self.actor,
            idempotency_key="discord-message:postgres-task",
        )

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(replay.mutation.uid, "TASK-POSTGRES-1")
        self.assertEqual(len(adapter.calls), 1)
        persisted = PostgresDurableGovernorStore().get_operation(first.operation.operation_id)
        assert persisted is not None
        self.assertEqual(persisted.status, "completed")
        self.assertEqual(persisted.result, {"uid": "TASK-POSTGRES-1"})
        self.assertNotIn("memo", persisted.parameters)
        self.assertIsNone(PostgresDurableGovernorStore().get_pending_payload(first.operation.operation_id))
        self.assertEqual(
            [record.outcome for record in PostgresDurableGovernorStore().audit_records(first.operation.operation_id)],
            ["accepted", "completed"],
        )

    def test_governed_memo_execution_is_durable_and_idempotent(self) -> None:
        adapter = FakeMemoAdapter()
        service = MemoMutationService(adapter)
        command = MemoMutationCommand("create", content="private memo body")

        first = service.execute_governed(
            GovernorOperations(PostgresDurableGovernorStore()),
            command,
            actor=self.actor,
            idempotency_key="discord-message:postgres-memo",
        )
        replay = service.execute_governed(
            GovernorOperations(PostgresDurableGovernorStore()),
            command,
            actor=self.actor,
            idempotency_key="discord-message:postgres-memo",
        )

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(replay.mutation.name, "memos/postgres-1")
        self.assertEqual(adapter.calls, [("create", "private memo body", "PRIVATE")])
        persisted = PostgresDurableGovernorStore().get_operation(first.operation.operation_id)
        assert persisted is not None
        self.assertEqual(persisted.status, "completed")
        self.assertEqual(persisted.result, {"name": "memos/postgres-1"})
        self.assertNotIn("content", persisted.parameters)
        self.assertEqual(persisted.parameters["contentFingerprint"]["bytes"], 17)
        self.assertIsNone(PostgresDurableGovernorStore().get_pending_payload(first.operation.operation_id))
        self.assertEqual(
            [record.outcome for record in PostgresDurableGovernorStore().audit_records(first.operation.operation_id)],
            ["accepted", "completed"],
        )


if __name__ == "__main__":
    unittest.main()
