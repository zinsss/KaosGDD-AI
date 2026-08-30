from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import secrets
import threading
from typing import Any, Literal


ActorType = Literal["user", "family_user", "service", "system"]
Scope = Literal["personal", "family", "clinic", "system"]
OperationStatus = Literal[
    "pending",
    "requires_confirmation",
    "confirmed",
    "completed",
    "failed",
    "expired",
    "cancelled",
]
ConfirmationStatus = Literal["pending", "approved", "expired", "cancelled"]
AuditOutcome = Literal[
    "accepted",
    "rejected",
    "requires_confirmation",
    "approved",
    "completed",
    "failed",
    "expired",
    "cancelled",
]


ACTOR_TYPES = {"user", "family_user", "service", "system"}
SCOPES = {"personal", "family", "clinic", "system"}
OPERATION_STATUSES = {
    "pending",
    "requires_confirmation",
    "confirmed",
    "completed",
    "failed",
    "expired",
    "cancelled",
}
CONFIRMATION_STATUSES = {"pending", "approved", "expired", "cancelled"}
AUDIT_OUTCOMES = {
    "accepted",
    "rejected",
    "requires_confirmation",
    "approved",
    "completed",
    "failed",
    "expired",
    "cancelled",
}
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
MAX_IDEMPOTENCY_KEY_CHARS = 200
MAX_PENDING_PAYLOAD_BYTES = 128 * 1024
INTERRUPTED_EXECUTION_GRACE = timedelta(hours=1)
PENDING_PAYLOAD_PROHIBITED_KEY_PARTS = {
    "attachment",
    "authorization",
    "base64",
    "binary",
    "cookie",
    "credential",
    "imagebytes",
    "password",
    "pdfbytes",
    "secret",
    "token",
}


class DurableGovernorError(ValueError):
    """Raised when a durable operation contract is invalid or stale."""


@dataclass(frozen=True)
class Actor:
    actor_type: ActorType
    actor_id: str
    scope: Scope

    def __post_init__(self) -> None:
        if self.actor_type not in ACTOR_TYPES:
            raise DurableGovernorError("actor_type_invalid")
        if self.scope not in SCOPES:
            raise DurableGovernorError("scope_invalid")
        if not TOKEN.fullmatch(self.actor_id):
            raise DurableGovernorError("actor_id_invalid")


@dataclass(frozen=True)
class OperationRequest:
    actor: Actor
    idempotency_key: str
    tool_name: str
    operation_type: str
    parameters: Mapping[str, Any]
    requires_confirmation: bool = False
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key or len(self.idempotency_key) > MAX_IDEMPOTENCY_KEY_CHARS:
            raise DurableGovernorError("idempotency_key_invalid")
        if not TOKEN.fullmatch(self.tool_name):
            raise DurableGovernorError("tool_name_invalid")
        if not TOKEN.fullmatch(self.operation_type):
            raise DurableGovernorError("operation_type_invalid")
        _canonical_json(self.parameters)
        if self.expires_at is not None:
            _require_aware_utc(self.expires_at, "expires_at")

    @property
    def request_hash(self) -> str:
        return stable_hash(
            {
                "toolName": self.tool_name,
                "operationType": self.operation_type,
                "parameters": self.parameters,
            }
        )


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    actor: Actor
    idempotency_key: str
    tool_name: str
    operation_type: str
    request_hash: str
    parameters: Mapping[str, Any]
    status: OperationStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    result: Mapping[str, Any] = field(default_factory=dict)
    error_code: str = ""


@dataclass(frozen=True)
class ConfirmationRecord:
    confirmation_id: str
    operation_id: str
    actor: Actor
    normalized_operation_hash: str
    status: ConfirmationStatus
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


@dataclass(frozen=True)
class PendingOperationPayload:
    operation_id: str
    payload_kind: str
    schema_version: int
    payload: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuditRecord:
    audit_id: str
    actor: Actor
    event_type: str
    outcome: AuditOutcome
    created_at: datetime
    operation_id: str = ""
    tool_name: str = ""
    idempotency_key: str = ""
    request_hash: str = ""
    reason: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)


def stable_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def new_operation_id() -> str:
    return f"op_{secrets.token_hex(16)}"


def new_confirmation_id() -> str:
    return f"conf_{secrets.token_hex(16)}"


def new_audit_id() -> str:
    return f"audit_{secrets.token_hex(16)}"


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise DurableGovernorError("parameters_not_json_serializable") from exc


def normalized_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached JSON object with tuples and other JSON values normalized."""

    return json.loads(_canonical_json(value))


def validate_pending_payload(
    payload_kind: str,
    payload: Mapping[str, Any],
    *,
    schema_version: int = 1,
) -> dict[str, Any]:
    """Validate restart payloads without allowing secrets or binary material."""

    if not TOKEN.fullmatch(payload_kind):
        raise DurableGovernorError("pending_payload_kind_invalid")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or not 1 <= schema_version <= 1000:
        raise DurableGovernorError("pending_payload_schema_version_invalid")
    normalized = normalized_json_object(payload)
    if len(_canonical_json(normalized).encode("utf-8")) > MAX_PENDING_PAYLOAD_BYTES:
        raise DurableGovernorError("pending_payload_too_large")
    for key in _mapping_keys(normalized):
        compact = re.sub(r"[^a-z0-9]", "", key.lower())
        if any(part in compact for part in PENDING_PAYLOAD_PROHIBITED_KEY_PARTS):
            raise DurableGovernorError("pending_payload_prohibited_key")
    return normalized


def _mapping_keys(value: Any):
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _mapping_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _mapping_keys(nested)


def _now() -> datetime:
    return datetime.now(UTC)


def _require_aware_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DurableGovernorError(f"{field_name}_must_be_timezone_aware")


class MemoryDurableGovernorStore:
    """Deterministic store used by tests and explicitly ephemeral runtimes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._operations: dict[str, OperationRecord] = {}
        self._idempotency: dict[tuple[str, str, str, str], str] = {}
        self._confirmations: dict[str, ConfirmationRecord] = {}
        self._pending_payloads: dict[str, PendingOperationPayload] = {}
        self._audit: list[AuditRecord] = []

    def start_operation(self, request: OperationRequest, *, now: datetime | None = None) -> tuple[OperationRecord, bool]:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        key = (
            request.actor.actor_type,
            request.actor.actor_id,
            request.actor.scope,
            request.idempotency_key,
        )
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id:
                existing = self._operations[existing_id]
                if existing.request_hash != request.request_hash:
                    self.record_audit(
                        actor=request.actor,
                        event_type="operation.idempotency_conflict",
                        outcome="rejected",
                        operation_id=existing.operation_id,
                        tool_name=request.tool_name,
                        idempotency_key=request.idempotency_key,
                        request_hash=request.request_hash,
                        reason="idempotency_key_reused_with_different_request",
                        now=timestamp,
                    )
                    raise DurableGovernorError("idempotency_key_conflict")
                return existing, False

            status: OperationStatus = "requires_confirmation" if request.requires_confirmation else "pending"
            operation = OperationRecord(
                operation_id=new_operation_id(),
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                tool_name=request.tool_name,
                operation_type=request.operation_type,
                request_hash=request.request_hash,
                parameters=normalized_json_object(request.parameters),
                status=status,
                created_at=timestamp,
                updated_at=timestamp,
                expires_at=request.expires_at,
            )
            self._operations[operation.operation_id] = operation
            self._idempotency[key] = operation.operation_id
            self.record_audit(
                actor=request.actor,
                event_type="operation.started",
                outcome="requires_confirmation" if request.requires_confirmation else "accepted",
                operation_id=operation.operation_id,
                tool_name=request.tool_name,
                idempotency_key=request.idempotency_key,
                request_hash=request.request_hash,
                now=timestamp,
            )
            return operation, True

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
        with self._lock:
            self.expire_stale_proposals(now=timestamp)
            operation, created = self.start_operation(request, now=timestamp)
            if not created:
                existing_confirmation = next(
                    (
                        confirmation
                        for confirmation in self._confirmations.values()
                        if confirmation.operation_id == operation.operation_id
                        and confirmation.status == "pending"
                        and timestamp < confirmation.expires_at
                    ),
                    None,
                )
                if existing_confirmation is None:
                    raise DurableGovernorError("operation_not_pending")
                return operation, False, existing_confirmation
            confirmation = self.create_confirmation(
                operation.operation_id,
                ttl=confirmation_ttl,
                now=timestamp,
            )
            self.save_pending_payload(
                operation.operation_id,
                payload_kind=payload_kind,
                payload=normalized_payload,
                schema_version=schema_version,
                now=timestamp,
            )
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
        with self._lock:
            operation = self._require_operation(operation_id)
            confirmation = ConfirmationRecord(
                confirmation_id=new_confirmation_id(),
                operation_id=operation.operation_id,
                actor=operation.actor,
                normalized_operation_hash=operation.request_hash,
                status="pending",
                created_at=timestamp,
                expires_at=timestamp + ttl,
            )
            self._confirmations[confirmation.confirmation_id] = confirmation
            self.record_audit(
                actor=operation.actor,
                event_type="confirmation.created",
                outcome="requires_confirmation",
                operation_id=operation.operation_id,
                tool_name=operation.tool_name,
                idempotency_key=operation.idempotency_key,
                request_hash=operation.request_hash,
                now=timestamp,
            )
            return confirmation

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
        with self._lock:
            confirmation = self._confirmations.get(confirmation_id)
            if confirmation is None:
                raise DurableGovernorError("confirmation_not_found")
            if confirmation.actor != actor:
                raise DurableGovernorError("confirmation_actor_mismatch")
            if confirmation.normalized_operation_hash != normalized_operation_hash:
                raise DurableGovernorError("confirmation_operation_mismatch")
            if confirmation.status == "expired":
                raise DurableGovernorError("confirmation_expired")
            if confirmation.status != "pending":
                raise DurableGovernorError("confirmation_not_pending")
            if timestamp >= confirmation.expires_at:
                expired = replace(confirmation, status="expired")
                self._confirmations[confirmation_id] = expired
                has_active_confirmation = any(
                    candidate.confirmation_id != confirmation_id
                    and candidate.operation_id == expired.operation_id
                    and candidate.status == "pending"
                    and timestamp < candidate.expires_at
                    for candidate in self._confirmations.values()
                )
                if not has_active_confirmation:
                    self._expire_operation(expired.operation_id, timestamp)
                    self._pending_payloads.pop(expired.operation_id, None)
                self.record_audit(
                    actor=actor,
                    event_type="confirmation.expired",
                    outcome="expired",
                    operation_id=expired.operation_id,
                    request_hash=expired.normalized_operation_hash,
                    now=timestamp,
                )
                raise DurableGovernorError("confirmation_expired")
            approved = replace(confirmation, status="approved", used_at=timestamp)
            self._confirmations[confirmation_id] = approved
            operation = self._require_operation(approved.operation_id)
            self._operations[operation.operation_id] = replace(
                operation,
                status="confirmed",
                updated_at=timestamp,
            )
            self.record_audit(
                actor=actor,
                event_type="confirmation.approved",
                outcome="approved",
                operation_id=approved.operation_id,
                tool_name=operation.tool_name,
                idempotency_key=operation.idempotency_key,
                request_hash=approved.normalized_operation_hash,
                now=timestamp,
            )
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
        with self._lock:
            operation = self._require_operation(operation_id)
            completed = replace(
                operation,
                status="completed",
                updated_at=timestamp,
                result=normalized_result,
                error_code="",
            )
            self._operations[operation_id] = completed
            self._pending_payloads.pop(operation_id, None)
            self.record_audit(
                actor=operation.actor,
                event_type="operation.completed",
                outcome="completed",
                operation_id=operation.operation_id,
                tool_name=operation.tool_name,
                idempotency_key=operation.idempotency_key,
                request_hash=operation.request_hash,
                now=timestamp,
            )
            return completed

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
        with self._lock:
            operation = self._require_operation(operation_id)
            failed = replace(operation, status="failed", updated_at=timestamp, error_code=error_code)
            self._operations[operation_id] = failed
            self._pending_payloads.pop(operation_id, None)
            self.record_audit(
                actor=operation.actor,
                event_type="operation.failed",
                outcome="failed",
                operation_id=operation.operation_id,
                tool_name=operation.tool_name,
                idempotency_key=operation.idempotency_key,
                request_hash=operation.request_hash,
                reason=error_code,
                now=timestamp,
            )
            return failed

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        with self._lock:
            return self._operations.get(operation_id)

    def get_confirmation(self, confirmation_id: str) -> ConfirmationRecord | None:
        with self._lock:
            return self._confirmations.get(confirmation_id)

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
        with self._lock:
            self._require_operation(operation_id)
            existing = self._pending_payloads.get(operation_id)
            record = PendingOperationPayload(
                operation_id=operation_id,
                payload_kind=payload_kind,
                schema_version=schema_version,
                payload=normalized,
                created_at=existing.created_at if existing is not None else timestamp,
                updated_at=timestamp,
            )
            self._pending_payloads[operation_id] = record
            return record

    def get_pending_payload(self, operation_id: str) -> PendingOperationPayload | None:
        with self._lock:
            return self._pending_payloads.get(operation_id)

    def delete_pending_payload(self, operation_id: str) -> None:
        with self._lock:
            self._pending_payloads.pop(operation_id, None)

    def expire_stale_proposals(self, *, now: datetime | None = None) -> int:
        timestamp = now or _now()
        _require_aware_utc(timestamp, "now")
        with self._lock:
            affected_operation_ids: set[str] = set()
            for confirmation_id, confirmation in tuple(self._confirmations.items()):
                if confirmation.status != "pending" or timestamp < confirmation.expires_at:
                    continue
                expired = replace(confirmation, status="expired")
                self._confirmations[confirmation_id] = expired
                affected_operation_ids.add(expired.operation_id)
                self.record_audit(
                    actor=expired.actor,
                    event_type="confirmation.expired",
                    outcome="expired",
                    operation_id=expired.operation_id,
                    request_hash=expired.normalized_operation_hash,
                    now=timestamp,
                )

            deleted = 0
            for operation_id in affected_operation_ids:
                has_active_confirmation = any(
                    confirmation.operation_id == operation_id
                    and confirmation.status == "pending"
                    and timestamp < confirmation.expires_at
                    for confirmation in self._confirmations.values()
                )
                if has_active_confirmation:
                    continue
                self._expire_operation(operation_id, timestamp)
                if self._pending_payloads.pop(operation_id, None) is not None:
                    deleted += 1

            interrupted_operation_ids = {
                confirmation.operation_id
                for confirmation in self._confirmations.values()
                if confirmation.status == "approved"
                and confirmation.expires_at + INTERRUPTED_EXECUTION_GRACE <= timestamp
                and (operation := self._operations.get(confirmation.operation_id)) is not None
                and operation.status == "confirmed"
                and confirmation.operation_id in self._pending_payloads
            }
            for operation_id in interrupted_operation_ids:
                operation = self._require_operation(operation_id)
                self._operations[operation_id] = replace(
                    operation,
                    status="failed",
                    updated_at=timestamp,
                    error_code="execution_interrupted",
                )
                self._pending_payloads.pop(operation_id, None)
                deleted += 1
                self.record_audit(
                    actor=operation.actor,
                    event_type="operation.failed",
                    outcome="failed",
                    operation_id=operation.operation_id,
                    tool_name=operation.tool_name,
                    idempotency_key=operation.idempotency_key,
                    request_hash=operation.request_hash,
                    reason="execution_interrupted",
                    now=timestamp,
                )
            return deleted

    def audit_records(self, operation_id: str | None = None) -> tuple[AuditRecord, ...]:
        with self._lock:
            if operation_id is None:
                return tuple(self._audit)
            return tuple(record for record in self._audit if record.operation_id == operation_id)

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
        if not event_type:
            raise DurableGovernorError("audit_event_type_required")
        if outcome not in AUDIT_OUTCOMES:
            raise DurableGovernorError("audit_outcome_invalid")
        _canonical_json(payload or {})
        record = AuditRecord(
            audit_id=new_audit_id(),
            actor=actor,
            event_type=event_type,
            outcome=outcome,
            created_at=timestamp,
            operation_id=operation_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
            payload=dict(payload or {}),
        )
        self._audit.append(record)
        return record

    def _require_operation(self, operation_id: str) -> OperationRecord:
        operation = self._operations.get(operation_id)
        if operation is None:
            raise DurableGovernorError("operation_not_found")
        return operation

    def _expire_operation(self, operation_id: str, timestamp: datetime) -> None:
        operation = self._require_operation(operation_id)
        if operation.status in {"pending", "requires_confirmation"}:
            self._operations[operation_id] = replace(operation, status="expired", updated_at=timestamp)
