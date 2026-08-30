"""PostgreSQL implementation of the durable Governor operation contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .durable import (
    AUDIT_OUTCOMES,
    TOKEN,
    Actor,
    AuditOutcome,
    AuditRecord,
    ConfirmationRecord,
    DurableGovernorError,
    INTERRUPTED_EXECUTION_GRACE,
    OperationRecord,
    OperationRequest,
    PendingOperationPayload,
    _now,
    _require_aware_utc,
    new_audit_id,
    new_confirmation_id,
    new_operation_id,
    normalized_json_object,
    validate_pending_payload,
)


ConnectionFactory = Callable[[], Any]

OPERATION_COLUMNS = """
    operation_id, actor_type, actor_id, scope, idempotency_key, tool_name,
    operation_type, request_hash, parameters, status, created_at, updated_at,
    expires_at, result, error_code
"""
CONFIRMATION_COLUMNS = """
    confirmation_id, operation_id, actor_type, actor_id, scope,
    normalized_operation_hash, status, created_at, expires_at, used_at
"""
PENDING_PAYLOAD_COLUMNS = """
    operation_id, payload_kind, schema_version, payload, created_at, updated_at
"""
AUDIT_COLUMNS = """
    audit_id, operation_id, actor_type, actor_id, scope, event_type, tool_name,
    idempotency_key, request_hash, outcome, reason, payload, created_at
"""


class PostgresDurableGovernorStore:
    """Transaction-safe production store for operations and confirmations."""

    def __init__(self, connection_factory: ConnectionFactory | None = None) -> None:
        if connection_factory is None:
            from .database import connect

            connection_factory = connect
        self._connect = connection_factory

    def start_operation(
        self,
        request: OperationRequest,
        *,
        now: datetime | None = None,
    ) -> tuple[OperationRecord, bool]:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        conflict = False
        with self._connect() as connection:
            self._expire_stale_proposals(connection, timestamp)
            operation, created, conflict = self._start_operation(connection, request, timestamp)
        if conflict:
            raise DurableGovernorError("idempotency_key_conflict")
        return operation, created

    def start_proposal(
        self,
        request: OperationRequest,
        *,
        payload_kind: str,
        payload: Mapping[str, Any],
        schema_version: int,
        confirmation_ttl: timedelta,
        now: datetime | None = None,
    ) -> tuple[OperationRecord, bool, ConfirmationRecord]:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        if confirmation_ttl <= timedelta():
            raise DurableGovernorError("confirmation_ttl_invalid")
        normalized_payload = validate_pending_payload(
            payload_kind,
            payload,
            schema_version=schema_version,
        )
        conflict = False
        error_code = ""
        confirmation: ConfirmationRecord | None = None
        with self._connect() as connection:
            self._expire_stale_proposals(connection, timestamp)
            operation, created, conflict = self._start_operation(connection, request, timestamp)
            if not conflict:
                if created:
                    confirmation = self._create_confirmation(
                        connection,
                        operation,
                        ttl=confirmation_ttl,
                        timestamp=timestamp,
                    )
                    self._save_pending_payload(
                        connection,
                        operation.operation_id,
                        payload_kind=payload_kind,
                        payload=normalized_payload,
                        schema_version=schema_version,
                        timestamp=timestamp,
                    )
                else:
                    row = connection.execute(
                        f"""
                        SELECT {CONFIRMATION_COLUMNS}
                          FROM governor_confirmations
                         WHERE operation_id = %s
                           AND status = 'pending'
                           AND expires_at > %s
                      ORDER BY created_at, confirmation_id
                         LIMIT 1
                         FOR UPDATE
                        """,
                        (operation.operation_id, timestamp),
                    ).fetchone()
                    if row is None:
                        error_code = "operation_not_pending"
                    else:
                        confirmation = _confirmation_from_row(row)
        if conflict:
            raise DurableGovernorError("idempotency_key_conflict")
        if error_code:
            raise DurableGovernorError(error_code)
        if confirmation is None:
            raise DurableGovernorError("operation_not_pending")
        return operation, created, confirmation

    def create_confirmation(
        self,
        operation_id: str,
        *,
        ttl: timedelta,
        now: datetime | None = None,
    ) -> ConfirmationRecord:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        if ttl <= timedelta():
            raise DurableGovernorError("confirmation_ttl_invalid")
        with self._connect() as connection:
            operation = self._require_operation(connection, operation_id, for_update=True)
            return self._create_confirmation(connection, operation, ttl=ttl, timestamp=timestamp)

    def approve_confirmation(
        self,
        confirmation_id: str,
        *,
        actor: Actor,
        normalized_operation_hash: str,
        now: datetime | None = None,
    ) -> ConfirmationRecord:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        error_code = ""
        approved: ConfirmationRecord | None = None
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {CONFIRMATION_COLUMNS} FROM governor_confirmations WHERE confirmation_id = %s FOR UPDATE",
                (confirmation_id,),
            ).fetchone()
            if row is None:
                error_code = "confirmation_not_found"
            else:
                confirmation = _confirmation_from_row(row)
                operation = self._require_operation(connection, confirmation.operation_id, for_update=True)
                if confirmation.actor != actor:
                    error_code = "confirmation_actor_mismatch"
                elif confirmation.normalized_operation_hash != normalized_operation_hash:
                    error_code = "confirmation_operation_mismatch"
                elif confirmation.status == "expired":
                    error_code = "confirmation_expired"
                elif confirmation.status != "pending":
                    error_code = "confirmation_not_pending"
                elif timestamp >= confirmation.expires_at:
                    connection.execute(
                        "UPDATE governor_confirmations SET status = 'expired' WHERE confirmation_id = %s",
                        (confirmation_id,),
                    )
                    has_active_confirmation = connection.execute(
                        """
                        SELECT 1
                          FROM governor_confirmations
                         WHERE operation_id = %s
                           AND confirmation_id <> %s
                           AND status = 'pending'
                           AND expires_at > %s
                         LIMIT 1
                        """,
                        (operation.operation_id, confirmation_id, timestamp),
                    ).fetchone()
                    if has_active_confirmation is None and operation.status in {"pending", "requires_confirmation"}:
                        connection.execute(
                            "UPDATE governor_operations SET status = 'expired', updated_at = %s WHERE operation_id = %s",
                            (timestamp, operation.operation_id),
                        )
                    if has_active_confirmation is None:
                        connection.execute(
                            "DELETE FROM governor_operation_payloads WHERE operation_id = %s",
                            (operation.operation_id,),
                        )
                    self._insert_audit(
                        connection,
                        actor=actor,
                        event_type="confirmation.expired",
                        outcome="expired",
                        operation_id=operation.operation_id,
                        request_hash=confirmation.normalized_operation_hash,
                        timestamp=timestamp,
                    )
                    error_code = "confirmation_expired"
                else:
                    row = connection.execute(
                        f"""
                        UPDATE governor_confirmations
                           SET status = 'approved', used_at = %s
                         WHERE confirmation_id = %s
                     RETURNING {CONFIRMATION_COLUMNS}
                        """,
                        (timestamp, confirmation_id),
                    ).fetchone()
                    connection.execute(
                        "UPDATE governor_operations SET status = 'confirmed', updated_at = %s WHERE operation_id = %s",
                        (timestamp, operation.operation_id),
                    )
                    approved = _confirmation_from_row(row)
                    self._insert_audit(
                        connection,
                        actor=actor,
                        event_type="confirmation.approved",
                        outcome="approved",
                        operation_id=operation.operation_id,
                        tool_name=operation.tool_name,
                        idempotency_key=operation.idempotency_key,
                        request_hash=confirmation.normalized_operation_hash,
                        timestamp=timestamp,
                    )
        if error_code:
            raise DurableGovernorError(error_code)
        if approved is None:
            raise DurableGovernorError("confirmation_not_found")
        return approved

    def complete_operation(
        self,
        operation_id: str,
        *,
        result: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> OperationRecord:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        normalized_result = normalized_json_object(result or {})
        with self._connect() as connection:
            operation = self._require_operation(connection, operation_id, for_update=True)
            row = connection.execute(
                f"""
                UPDATE governor_operations
                   SET status = 'completed', updated_at = %s, result = %s, error_code = ''
                 WHERE operation_id = %s
             RETURNING {OPERATION_COLUMNS}
                """,
                (timestamp, Jsonb(normalized_result), operation_id),
            ).fetchone()
            connection.execute(
                "DELETE FROM governor_operation_payloads WHERE operation_id = %s",
                (operation_id,),
            )
            self._insert_audit(
                connection,
                actor=operation.actor,
                event_type="operation.completed",
                outcome="completed",
                operation_id=operation.operation_id,
                tool_name=operation.tool_name,
                idempotency_key=operation.idempotency_key,
                request_hash=operation.request_hash,
                timestamp=timestamp,
            )
            return _operation_from_row(row)

    def fail_operation(
        self,
        operation_id: str,
        *,
        error_code: str,
        now: datetime | None = None,
    ) -> OperationRecord:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        if not TOKEN.fullmatch(error_code):
            raise DurableGovernorError("error_code_invalid")
        with self._connect() as connection:
            operation = self._require_operation(connection, operation_id, for_update=True)
            row = connection.execute(
                f"""
                UPDATE governor_operations
                   SET status = 'failed', updated_at = %s, error_code = %s
                 WHERE operation_id = %s
             RETURNING {OPERATION_COLUMNS}
                """,
                (timestamp, error_code, operation_id),
            ).fetchone()
            connection.execute(
                "DELETE FROM governor_operation_payloads WHERE operation_id = %s",
                (operation_id,),
            )
            self._insert_audit(
                connection,
                actor=operation.actor,
                event_type="operation.failed",
                outcome="failed",
                operation_id=operation.operation_id,
                tool_name=operation.tool_name,
                idempotency_key=operation.idempotency_key,
                request_hash=operation.request_hash,
                reason=error_code,
                timestamp=timestamp,
            )
            return _operation_from_row(row)

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {OPERATION_COLUMNS} FROM governor_operations WHERE operation_id = %s",
                (operation_id,),
            ).fetchone()
        return _operation_from_row(row) if row is not None else None

    def get_confirmation(self, confirmation_id: str) -> ConfirmationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {CONFIRMATION_COLUMNS} FROM governor_confirmations WHERE confirmation_id = %s",
                (confirmation_id,),
            ).fetchone()
        return _confirmation_from_row(row) if row is not None else None

    def save_pending_payload(
        self,
        operation_id: str,
        *,
        payload_kind: str,
        payload: Mapping[str, Any],
        schema_version: int = 1,
        now: datetime | None = None,
    ) -> PendingOperationPayload:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        normalized = validate_pending_payload(payload_kind, payload, schema_version=schema_version)
        with self._connect() as connection:
            self._require_operation(connection, operation_id, for_update=True)
            return self._save_pending_payload(
                connection,
                operation_id,
                payload_kind=payload_kind,
                payload=normalized,
                schema_version=schema_version,
                timestamp=timestamp,
            )

    def get_pending_payload(self, operation_id: str) -> PendingOperationPayload | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {PENDING_PAYLOAD_COLUMNS} FROM governor_operation_payloads WHERE operation_id = %s",
                (operation_id,),
            ).fetchone()
        return _pending_payload_from_row(row) if row is not None else None

    def delete_pending_payload(self, operation_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM governor_operation_payloads WHERE operation_id = %s",
                (operation_id,),
            )

    def expire_stale_proposals(self, *, now: datetime | None = None) -> int:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        with self._connect() as connection:
            return self._expire_stale_proposals(connection, timestamp)

    def record_audit(
        self,
        *,
        actor: Actor,
        event_type: str,
        outcome: AuditOutcome,
        now: datetime | None = None,
        operation_id: str = "",
        tool_name: str = "",
        idempotency_key: str = "",
        request_hash: str = "",
        reason: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> AuditRecord:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        with self._connect() as connection:
            return self._insert_audit(
                connection,
                actor=actor,
                event_type=event_type,
                outcome=outcome,
                operation_id=operation_id,
                tool_name=tool_name,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                reason=reason,
                payload=payload,
                timestamp=timestamp,
            )

    def audit_records(self, operation_id: str | None = None) -> tuple[AuditRecord, ...]:
        with self._connect() as connection:
            if operation_id is None:
                rows = connection.execute(
                    f"SELECT {AUDIT_COLUMNS} FROM governor_audit_records ORDER BY created_at, audit_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT {AUDIT_COLUMNS}
                      FROM governor_audit_records
                     WHERE operation_id = %s
                  ORDER BY created_at, audit_id
                    """,
                    (operation_id,),
                ).fetchall()
        return tuple(_audit_from_row(row) for row in rows)

    def _start_operation(
        self,
        connection,
        request: OperationRequest,
        timestamp: datetime,
    ) -> tuple[OperationRecord, bool, bool]:
        operation_id = new_operation_id()
        status = "requires_confirmation" if request.requires_confirmation else "pending"
        parameters = normalized_json_object(request.parameters)
        row = connection.execute(
            f"""
            INSERT INTO governor_operations (
                operation_id, actor_type, actor_id, scope, idempotency_key,
                tool_name, operation_type, request_hash, parameters, status,
                created_at, updated_at, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (actor_type, actor_id, scope, idempotency_key) DO NOTHING
            RETURNING {OPERATION_COLUMNS}
            """,
            (
                operation_id,
                request.actor.actor_type,
                request.actor.actor_id,
                request.actor.scope,
                request.idempotency_key,
                request.tool_name,
                request.operation_type,
                request.request_hash,
                Jsonb(parameters),
                status,
                timestamp,
                timestamp,
                request.expires_at,
            ),
        ).fetchone()
        if row is not None:
            operation = _operation_from_row(row)
            self._insert_audit(
                connection,
                actor=request.actor,
                event_type="operation.started",
                outcome="requires_confirmation" if request.requires_confirmation else "accepted",
                operation_id=operation.operation_id,
                tool_name=request.tool_name,
                idempotency_key=request.idempotency_key,
                request_hash=request.request_hash,
                timestamp=timestamp,
            )
            return operation, True, False

        row = connection.execute(
            f"""
            SELECT {OPERATION_COLUMNS}
              FROM governor_operations
             WHERE actor_type = %s AND actor_id = %s AND scope = %s AND idempotency_key = %s
             FOR UPDATE
            """,
            (
                request.actor.actor_type,
                request.actor.actor_id,
                request.actor.scope,
                request.idempotency_key,
            ),
        ).fetchone()
        if row is None:
            raise DurableGovernorError("operation_not_found")
        operation = _operation_from_row(row)
        if operation.request_hash == request.request_hash:
            return operation, False, False
        self._insert_audit(
            connection,
            actor=request.actor,
            event_type="operation.idempotency_conflict",
            outcome="rejected",
            operation_id=operation.operation_id,
            tool_name=request.tool_name,
            idempotency_key=request.idempotency_key,
            request_hash=request.request_hash,
            reason="idempotency_key_reused_with_different_request",
            timestamp=timestamp,
        )
        return operation, False, True

    def _expire_stale_proposals(self, connection, timestamp: datetime) -> int:
        rows = connection.execute(
            f"""
            SELECT {CONFIRMATION_COLUMNS}
              FROM governor_confirmations
             WHERE status = 'pending' AND expires_at <= %s
             FOR UPDATE
            """,
            (timestamp,),
        ).fetchall()
        affected_operation_ids: set[str] = set()
        for row in rows:
            confirmation = _confirmation_from_row(row)
            connection.execute(
                "UPDATE governor_confirmations SET status = 'expired' WHERE confirmation_id = %s",
                (confirmation.confirmation_id,),
            )
            affected_operation_ids.add(confirmation.operation_id)
            self._insert_audit(
                connection,
                actor=confirmation.actor,
                event_type="confirmation.expired",
                outcome="expired",
                operation_id=confirmation.operation_id,
                request_hash=confirmation.normalized_operation_hash,
                timestamp=timestamp,
            )

        deleted = 0
        for operation_id in affected_operation_ids:
            has_active_confirmation = connection.execute(
                """
                SELECT 1
                  FROM governor_confirmations
                 WHERE operation_id = %s
                   AND status = 'pending'
                   AND expires_at > %s
                 LIMIT 1
                """,
                (operation_id, timestamp),
            ).fetchone()
            if has_active_confirmation is not None:
                continue
            connection.execute(
                """
                UPDATE governor_operations
                   SET status = 'expired', updated_at = %s
                 WHERE operation_id = %s
                   AND status IN ('pending', 'requires_confirmation')
                """,
                (timestamp, operation_id),
            )
            cursor = connection.execute(
                "DELETE FROM governor_operation_payloads WHERE operation_id = %s",
                (operation_id,),
            )
            deleted += cursor.rowcount

        interrupted_rows = connection.execute(
            """
            SELECT operation_id
              FROM governor_operations
             WHERE status = 'confirmed'
               AND operation_id IN (
                    SELECT payload.operation_id
                      FROM governor_operation_payloads AS payload
                      JOIN governor_confirmations AS confirmation
                        ON confirmation.operation_id = payload.operation_id
                     WHERE confirmation.status = 'approved'
                       AND confirmation.expires_at <= %s
               )
             FOR UPDATE
            """,
            (timestamp - INTERRUPTED_EXECUTION_GRACE,),
        ).fetchall()
        for row in interrupted_rows:
            operation = self._require_operation(connection, str(row[0]), for_update=False)
            connection.execute(
                """
                UPDATE governor_operations
                   SET status = 'failed', updated_at = %s, error_code = 'execution_interrupted'
                 WHERE operation_id = %s
                """,
                (timestamp, operation.operation_id),
            )
            cursor = connection.execute(
                "DELETE FROM governor_operation_payloads WHERE operation_id = %s",
                (operation.operation_id,),
            )
            deleted += cursor.rowcount
            self._insert_audit(
                connection,
                actor=operation.actor,
                event_type="operation.failed",
                outcome="failed",
                operation_id=operation.operation_id,
                tool_name=operation.tool_name,
                idempotency_key=operation.idempotency_key,
                request_hash=operation.request_hash,
                reason="execution_interrupted",
                timestamp=timestamp,
            )
        return deleted

    def _create_confirmation(
        self,
        connection,
        operation: OperationRecord,
        *,
        ttl: timedelta,
        timestamp: datetime,
    ) -> ConfirmationRecord:
        confirmation_id = new_confirmation_id()
        row = connection.execute(
            f"""
            INSERT INTO governor_confirmations (
                confirmation_id, operation_id, actor_type, actor_id, scope,
                normalized_operation_hash, status, created_at, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s)
            RETURNING {CONFIRMATION_COLUMNS}
            """,
            (
                confirmation_id,
                operation.operation_id,
                operation.actor.actor_type,
                operation.actor.actor_id,
                operation.actor.scope,
                operation.request_hash,
                timestamp,
                timestamp + ttl,
            ),
        ).fetchone()
        confirmation = _confirmation_from_row(row)
        self._insert_audit(
            connection,
            actor=operation.actor,
            event_type="confirmation.created",
            outcome="requires_confirmation",
            operation_id=operation.operation_id,
            tool_name=operation.tool_name,
            idempotency_key=operation.idempotency_key,
            request_hash=operation.request_hash,
            timestamp=timestamp,
        )
        return confirmation

    def _save_pending_payload(
        self,
        connection,
        operation_id: str,
        *,
        payload_kind: str,
        payload: Mapping[str, Any],
        schema_version: int,
        timestamp: datetime,
    ) -> PendingOperationPayload:
        row = connection.execute(
            f"""
            INSERT INTO governor_operation_payloads (
                operation_id, payload_kind, schema_version, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (operation_id) DO UPDATE
                    SET payload_kind = EXCLUDED.payload_kind,
                        schema_version = EXCLUDED.schema_version,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
            RETURNING {PENDING_PAYLOAD_COLUMNS}
            """,
            (
                operation_id,
                payload_kind,
                schema_version,
                Jsonb(normalized_json_object(payload)),
                timestamp,
                timestamp,
            ),
        ).fetchone()
        return _pending_payload_from_row(row)

    def _require_operation(self, connection, operation_id: str, *, for_update: bool) -> OperationRecord:
        suffix = " FOR UPDATE" if for_update else ""
        row = connection.execute(
            f"SELECT {OPERATION_COLUMNS} FROM governor_operations WHERE operation_id = %s{suffix}",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise DurableGovernorError("operation_not_found")
        return _operation_from_row(row)

    def _insert_audit(
        self,
        connection,
        *,
        actor: Actor,
        event_type: str,
        outcome: AuditOutcome,
        timestamp: datetime,
        operation_id: str = "",
        tool_name: str = "",
        idempotency_key: str = "",
        request_hash: str = "",
        reason: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> AuditRecord:
        if not event_type:
            raise DurableGovernorError("audit_event_type_required")
        if outcome not in AUDIT_OUTCOMES:
            raise DurableGovernorError("audit_outcome_invalid")
        normalized_payload = normalized_json_object(payload or {})
        audit_id = new_audit_id()
        row = connection.execute(
            f"""
            INSERT INTO governor_audit_records (
                audit_id, operation_id, actor_type, actor_id, scope, event_type,
                tool_name, idempotency_key, request_hash, outcome, reason, payload,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {AUDIT_COLUMNS}
            """,
            (
                audit_id,
                operation_id or None,
                actor.actor_type,
                actor.actor_id,
                actor.scope,
                event_type,
                tool_name,
                idempotency_key,
                request_hash,
                outcome,
                reason,
                Jsonb(normalized_payload),
                timestamp,
            ),
        ).fetchone()
        return _audit_from_row(row)


def _operation_from_row(row) -> OperationRecord:
    return OperationRecord(
        operation_id=str(row[0]),
        actor=Actor(str(row[1]), str(row[2]), str(row[3])),  # type: ignore[arg-type]
        idempotency_key=str(row[4]),
        tool_name=str(row[5]),
        operation_type=str(row[6]),
        request_hash=str(row[7]),
        parameters=normalized_json_object(row[8] or {}),
        status=str(row[9]),  # type: ignore[arg-type]
        created_at=row[10],
        updated_at=row[11],
        expires_at=row[12],
        result=normalized_json_object(row[13] or {}),
        error_code=str(row[14] or ""),
    )


def _confirmation_from_row(row) -> ConfirmationRecord:
    return ConfirmationRecord(
        confirmation_id=str(row[0]),
        operation_id=str(row[1]),
        actor=Actor(str(row[2]), str(row[3]), str(row[4])),  # type: ignore[arg-type]
        normalized_operation_hash=str(row[5]),
        status=str(row[6]),  # type: ignore[arg-type]
        created_at=row[7],
        expires_at=row[8],
        used_at=row[9],
    )


def _pending_payload_from_row(row) -> PendingOperationPayload:
    return PendingOperationPayload(
        operation_id=str(row[0]),
        payload_kind=str(row[1]),
        schema_version=int(row[2]),
        payload=normalized_json_object(row[3] or {}),
        created_at=row[4],
        updated_at=row[5],
    )


def _audit_from_row(row) -> AuditRecord:
    return AuditRecord(
        audit_id=str(row[0]),
        operation_id=str(row[1] or ""),
        actor=Actor(str(row[2]), str(row[3]), str(row[4])),  # type: ignore[arg-type]
        event_type=str(row[5]),
        tool_name=str(row[6] or ""),
        idempotency_key=str(row[7] or ""),
        request_hash=str(row[8] or ""),
        outcome=str(row[9]),  # type: ignore[arg-type]
        reason=str(row[10] or ""),
        payload=normalized_json_object(row[11] or {}),
        created_at=row[12],
    )
