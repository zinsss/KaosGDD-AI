from datetime import UTC, datetime, timedelta
from pathlib import Path
import unittest

from kaos_governor.durable import (
    Actor,
    DurableGovernorError,
    MemoryDurableGovernorStore,
    OperationRequest,
    validate_pending_payload,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


class DurableGovernorTests(unittest.TestCase):
    def actor(self) -> Actor:
        return Actor(actor_type="user", actor_id="discord:1234", scope="personal")

    def request(self, **overrides) -> OperationRequest:
        values = {
            "actor": self.actor(),
            "idempotency_key": "discord-message-1",
            "tool_name": "kaos.memos",
            "operation_type": "search",
            "parameters": {"query": "printer", "limit": 5},
        }
        values.update(overrides)
        return OperationRequest(**values)

    def test_operation_start_records_actor_scope_idempotency_and_audit(self) -> None:
        store = MemoryDurableGovernorStore()
        operation, created = store.start_operation(self.request(), now=NOW)
        duplicate, duplicate_created = store.start_operation(self.request(), now=NOW + timedelta(seconds=1))
        audit = store.audit_records(operation.operation_id)

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(operation.operation_id, duplicate.operation_id)
        self.assertEqual(operation.actor.scope, "personal")
        self.assertEqual(operation.status, "pending")
        self.assertEqual(operation.parameters, {"query": "printer", "limit": 5})
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0].outcome, "accepted")

    def test_idempotency_key_cannot_be_reused_for_a_different_request(self) -> None:
        store = MemoryDurableGovernorStore()
        operation, _ = store.start_operation(self.request(), now=NOW)

        with self.assertRaisesRegex(DurableGovernorError, "idempotency_key_conflict"):
            store.start_operation(self.request(parameters={"query": "different"}), now=NOW)

        audit = store.audit_records(operation.operation_id)
        self.assertEqual(audit[-1].outcome, "rejected")
        self.assertEqual(audit[-1].reason, "idempotency_key_reused_with_different_request")

    def test_confirmation_approval_binds_actor_operation_hash_and_expiry(self) -> None:
        store = MemoryDurableGovernorStore()
        operation, _ = store.start_operation(self.request(requires_confirmation=True), now=NOW)
        confirmation = store.create_confirmation(operation.operation_id, ttl=timedelta(minutes=5), now=NOW)

        approved = store.approve_confirmation(
            confirmation.confirmation_id,
            actor=self.actor(),
            normalized_operation_hash=operation.request_hash,
            now=NOW + timedelta(minutes=2),
        )
        updated = store.get_operation(operation.operation_id)

        self.assertEqual(approved.status, "approved")
        self.assertIsNotNone(approved.used_at)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "confirmed")

    def test_expired_confirmation_expires_the_waiting_operation(self) -> None:
        store = MemoryDurableGovernorStore()
        operation, _, confirmation = store.start_proposal(
            self.request(requires_confirmation=True),
            payload_kind="memo.edit",
            payload={"name": "memos/42", "newContent": "updated"},
            schema_version=1,
            confirmation_ttl=timedelta(minutes=5),
            now=NOW,
        )

        with self.assertRaisesRegex(DurableGovernorError, "confirmation_expired"):
            store.approve_confirmation(
                confirmation.confirmation_id,
                actor=self.actor(),
                normalized_operation_hash=operation.request_hash,
                now=NOW + timedelta(minutes=5),
            )

        updated = store.get_operation(operation.operation_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "expired")
        self.assertIsNone(store.get_pending_payload(operation.operation_id))

    def test_pending_payload_rejects_secret_binary_and_oversize_fields(self) -> None:
        for payload in (
            {"apiToken": "secret"},
            {"nested": {"attachmentBase64": "AA=="}},
            {"password": "secret"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(DurableGovernorError, "pending_payload_prohibited_key"):
                    validate_pending_payload("memo.create", payload)

        with self.assertRaisesRegex(DurableGovernorError, "pending_payload_too_large"):
            validate_pending_payload("memo.create", {"content": "x" * (128 * 1024)})

    def test_invalid_proposal_ttl_does_not_leave_a_partial_operation(self) -> None:
        store = MemoryDurableGovernorStore()
        request = self.request(requires_confirmation=True)

        with self.assertRaisesRegex(DurableGovernorError, "confirmation_ttl_invalid"):
            store.start_proposal(
                request,
                payload_kind="memo.create",
                payload={"content": "safe"},
                schema_version=1,
                confirmation_ttl=timedelta(),
                now=NOW,
            )

        operation, created = store.start_operation(request, now=NOW)
        self.assertTrue(created)
        self.assertIsNone(store.get_pending_payload(operation.operation_id))

    def test_stale_proposal_cleanup_removes_unapproved_sensitive_payload(self) -> None:
        store = MemoryDurableGovernorStore()
        operation, _, confirmation = store.start_proposal(
            self.request(requires_confirmation=True),
            payload_kind="memo.create",
            payload={"content": "temporary sensitive memo"},
            schema_version=1,
            confirmation_ttl=timedelta(minutes=5),
            now=NOW,
        )

        deleted = store.expire_stale_proposals(now=NOW + timedelta(minutes=5))

        self.assertEqual(deleted, 1)
        self.assertEqual(store.get_operation(operation.operation_id).status, "expired")
        self.assertEqual(store.get_confirmation(confirmation.confirmation_id).status, "expired")
        self.assertIsNone(store.get_pending_payload(operation.operation_id))

    def test_interrupted_confirmed_execution_is_failed_and_cleaned_after_grace(self) -> None:
        store = MemoryDurableGovernorStore()
        operation, _, confirmation = store.start_proposal(
            self.request(requires_confirmation=True),
            payload_kind="memo.create",
            payload={"content": "temporary sensitive memo"},
            schema_version=1,
            confirmation_ttl=timedelta(minutes=5),
            now=NOW,
        )
        store.approve_confirmation(
            confirmation.confirmation_id,
            actor=self.actor(),
            normalized_operation_hash=operation.request_hash,
            now=NOW + timedelta(minutes=1),
        )

        deleted = store.expire_stale_proposals(now=NOW + timedelta(hours=1, minutes=5))

        updated = store.get_operation(operation.operation_id)
        self.assertEqual(deleted, 1)
        self.assertEqual(updated.status, "failed")
        self.assertEqual(updated.error_code, "execution_interrupted")
        self.assertIsNone(store.get_pending_payload(operation.operation_id))

    def test_actor_and_scope_are_validated_before_persistence(self) -> None:
        with self.assertRaisesRegex(DurableGovernorError, "scope_invalid"):
            Actor(actor_type="user", actor_id="discord:1", scope="public")  # type: ignore[arg-type]
        with self.assertRaisesRegex(DurableGovernorError, "actor_id_invalid"):
            Actor(actor_type="user", actor_id="../secret", scope="personal")

    def test_completed_and_failed_operations_append_audit_records(self) -> None:
        store = MemoryDurableGovernorStore()
        operation, _ = store.start_operation(self.request(), now=NOW)
        completed = store.complete_operation(operation.operation_id, result={"memoCount": 1}, now=NOW)
        failed = store.fail_operation(operation.operation_id, error_code="downstream_timeout", now=NOW)
        outcomes = [record.outcome for record in store.audit_records(operation.operation_id)]

        self.assertEqual(completed.status, "completed")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(outcomes, ["accepted", "completed", "failed"])

    def test_postgresql_foundation_migration_declares_required_tables_and_indexes(self) -> None:
        migration_path = next(
            (
                parent / "migrations" / "001_governor_foundation.sql"
                for parent in Path(__file__).resolve().parents
                if (parent / "migrations" / "001_governor_foundation.sql").exists()
            ),
            None,
        )
        self.assertIsNotNone(migration_path)
        migration = migration_path.read_text(encoding="utf-8")

        for required in (
            "CREATE TABLE IF NOT EXISTS governor_operations",
            "CREATE TABLE IF NOT EXISTS governor_confirmations",
            "CREATE TABLE IF NOT EXISTS governor_audit_records",
            "governor_operations_actor_idempotency_idx",
            "governor_confirmations_expiry_idx",
            "governor_audit_records_actor_idx",
        ):
            self.assertIn(required, migration)

    def test_postgresql_payload_migration_is_additive_and_constrained(self) -> None:
        migration_path = next(
            (
                parent / "migrations" / "005_durable_operation_payloads.sql"
                for parent in Path(__file__).resolve().parents
                if (parent / "migrations" / "005_durable_operation_payloads.sql").exists()
            ),
            None,
        )
        self.assertIsNotNone(migration_path)
        migration = migration_path.read_text(encoding="utf-8")

        for required in (
            "ADD COLUMN IF NOT EXISTS parameters jsonb",
            "CREATE TABLE IF NOT EXISTS governor_operation_payloads",
            "PRIMARY KEY REFERENCES governor_operations(operation_id) ON DELETE CASCADE",
            "CHECK (jsonb_typeof(payload) = 'object')",
            "governor_operation_payloads_updated_idx",
        ):
            self.assertIn(required, migration)


if __name__ == "__main__":
    unittest.main()
