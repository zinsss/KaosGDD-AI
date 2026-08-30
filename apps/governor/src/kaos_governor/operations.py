"""Transport-neutral lifecycle boundary for deterministic Governor operations.

This module intentionally owns only the operation lifecycle in the first
migration phase. Domain handlers remain where they are and can move behind
this boundary incrementally without changing the HTTP or Discord contracts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from .durable import (
    Actor,
    AuditOutcome,
    AuditRecord,
    ConfirmationRecord,
    DurableGovernorError,
    MemoryDurableGovernorStore,
    OperationRecord,
    OperationRequest,
    PendingOperationPayload,
)


DEFAULT_CONFIRMATION_TTL = timedelta(minutes=10)


class DurableOperationStore(Protocol):
    """Storage contract required by :class:`GovernorOperations`.

    The protocol keeps the operation boundary independent of the current
    in-memory implementation and provides the seam for the PostgreSQL store.
    """

    def start_operation(
        self,
        request: OperationRequest,
        *,
        now: datetime | None = None,
    ) -> tuple[OperationRecord, bool]: ...

    def create_confirmation(
        self,
        operation_id: str,
        *,
        ttl: timedelta,
        now: datetime | None = None,
    ) -> ConfirmationRecord: ...

    def start_proposal(
        self,
        request: OperationRequest,
        *,
        payload_kind: str,
        payload: Mapping[str, Any],
        schema_version: int,
        confirmation_ttl: timedelta,
        now: datetime | None = None,
    ) -> tuple[OperationRecord, bool, ConfirmationRecord]: ...

    def approve_confirmation(
        self,
        confirmation_id: str,
        *,
        actor: Actor,
        normalized_operation_hash: str,
        now: datetime | None = None,
    ) -> ConfirmationRecord: ...

    def complete_operation(
        self,
        operation_id: str,
        *,
        result: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> OperationRecord: ...

    def fail_operation(
        self,
        operation_id: str,
        *,
        error_code: str,
        now: datetime | None = None,
    ) -> OperationRecord: ...

    def get_operation(self, operation_id: str) -> OperationRecord | None: ...

    def get_confirmation(self, confirmation_id: str) -> ConfirmationRecord | None: ...

    def get_pending_payload(self, operation_id: str) -> PendingOperationPayload | None: ...

    def delete_pending_payload(self, operation_id: str) -> None: ...

    def expire_stale_proposals(self, *, now: datetime | None = None) -> int: ...

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
    ) -> AuditRecord: ...


@dataclass(frozen=True)
class OperationSubmission:
    """Result of submitting a normalized operation to the Governor."""

    operation: OperationRecord
    created: bool
    confirmation: ConfirmationRecord | None = None


@dataclass(frozen=True)
class OperationProposal:
    """A submitted mutation with its required confirmation token."""

    operation: OperationRecord
    created: bool
    confirmation: ConfirmationRecord


@dataclass(frozen=True)
class ApprovedOperation:
    """Confirmation and operation records after a successful approval."""

    operation: OperationRecord
    confirmation: ConfirmationRecord


class GovernorOperations:
    """Single deterministic entry point for operation lifecycle decisions.

    Transports submit already-normalized :class:`OperationRequest` values.
    This class owns idempotency, confirmation, audit-state transitions, and
    completion state. It deliberately has no Discord or HTTP dependency.
    """

    def __init__(
        self,
        store: DurableOperationStore | None = None,
        *,
        confirmation_ttl: timedelta = DEFAULT_CONFIRMATION_TTL,
    ) -> None:
        if confirmation_ttl <= timedelta():
            raise DurableGovernorError("confirmation_ttl_invalid")
        self._store = store if store is not None else MemoryDurableGovernorStore()
        self._confirmation_ttl = confirmation_ttl

    @property
    def store(self) -> DurableOperationStore:
        return self._store

    def submit(
        self,
        request: OperationRequest,
        *,
        confirmation_ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> OperationSubmission:
        """Start an operation and issue confirmation when policy requires it."""

        operation, created = self._store.start_operation(request, now=now)
        confirmation = None
        if request.requires_confirmation:
            confirmation = self._store.create_confirmation(
                operation.operation_id,
                ttl=confirmation_ttl or self._confirmation_ttl,
                now=now,
            )
        return OperationSubmission(
            operation=operation,
            created=created,
            confirmation=confirmation,
        )

    def approve(
        self,
        confirmation_id: str,
        *,
        actor: Actor,
        now: datetime | None = None,
    ) -> ApprovedOperation:
        """Approve exactly the operation hash bound to a confirmation token."""

        confirmation = self._store.get_confirmation(confirmation_id)
        if confirmation is None:
            raise DurableGovernorError("confirmation_not_found")
        operation = self._store.get_operation(confirmation.operation_id)
        if operation is None:
            raise DurableGovernorError("operation_not_found")
        approved = self._store.approve_confirmation(
            confirmation_id,
            actor=actor,
            normalized_operation_hash=operation.request_hash,
            now=now,
        )
        updated = self._store.get_operation(operation.operation_id)
        if updated is None:
            raise DurableGovernorError("operation_not_found")
        return ApprovedOperation(operation=updated, confirmation=approved)

    def propose(
        self,
        request: OperationRequest,
        *,
        pending_kind: str,
        pending_payload: Mapping[str, Any],
        pending_schema_version: int = 1,
        confirmation_ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> OperationProposal:
        """Submit a mutation whose normalized policy requires confirmation."""

        if not request.requires_confirmation:
            raise DurableGovernorError("confirmation_not_required")
        operation, created, confirmation = self._store.start_proposal(
            request,
            payload_kind=pending_kind,
            payload=pending_payload,
            schema_version=pending_schema_version,
            confirmation_ttl=confirmation_ttl or self._confirmation_ttl,
            now=now,
        )
        return OperationProposal(
            operation=operation,
            created=created,
            confirmation=confirmation,
        )

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        return self._store.get_operation(operation_id)

    def get_confirmation(self, confirmation_id: str) -> ConfirmationRecord | None:
        return self._store.get_confirmation(confirmation_id)

    def get_pending_payload(self, operation_id: str) -> PendingOperationPayload | None:
        return self._store.get_pending_payload(operation_id)

    def delete_pending_payload(self, operation_id: str) -> None:
        self._store.delete_pending_payload(operation_id)

    def expire_stale_proposals(self, *, now: datetime | None = None) -> int:
        """Expire unused confirmations and remove their short-lived payloads."""

        return self._store.expire_stale_proposals(now=now)

    def complete(
        self,
        operation_id: str,
        *,
        result: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> OperationRecord:
        return self._store.complete_operation(operation_id, result=result, now=now)

    def fail(
        self,
        operation_id: str,
        *,
        error_code: str,
        now: datetime | None = None,
    ) -> OperationRecord:
        return self._store.fail_operation(operation_id, error_code=error_code, now=now)

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
        return self._store.record_audit(
            actor=actor,
            event_type=event_type,
            outcome=outcome,
            now=now,
            operation_id=operation_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
            payload=payload,
        )
