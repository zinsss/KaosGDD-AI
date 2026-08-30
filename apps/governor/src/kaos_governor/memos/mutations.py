"""Deterministic Memos mutation handlers owned by KaosGovernor.

Transports own authentication, confirmation presentation, and response
formatting. This module owns validation and the final dispatch to the
authoritative Memos adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from typing import Protocol

from ..durable import Actor, OperationRecord, OperationRequest
from ..operations import GovernorOperations
from .service import MAX_MEMO_CONTENT_CHARACTERS, MEMO_NAME


MEMO_OPERATION_TYPES = frozenset({"create", "edit", "delete"})


class MemoMutationError(ValueError):
    """A deterministic memo command failed Governor validation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MemoMutationRecord(Protocol):
    """Minimum memo result returned by the authoritative adapter."""

    @property
    def name(self) -> str: ...

    @property
    def content(self) -> str: ...


class MemoMutationAdapter(Protocol):
    """Narrow authoritative adapter contract used by memo handlers."""

    def create(self, content: object, *, visibility: str = "PRIVATE") -> MemoMutationRecord: ...

    def update(self, name: object, content: object) -> MemoMutationRecord: ...

    def delete(self, name: object) -> None: ...


@dataclass(frozen=True)
class MemoMutationCommand:
    """A normalized memo mutation ready for deterministic execution."""

    operation_type: str
    name: str = ""
    content: str = ""

    def __post_init__(self) -> None:
        if self.operation_type not in MEMO_OPERATION_TYPES:
            raise MemoMutationError("memo_operation_not_registered")
        if self.operation_type in {"edit", "delete"} and not MEMO_NAME.fullmatch(self.name):
            raise MemoMutationError("memo_name_invalid")
        if self.operation_type in {"create", "edit"}:
            if not self.content.strip():
                raise MemoMutationError("memo_content_required")
            if len(self.content) > MAX_MEMO_CONTENT_CHARACTERS:
                raise MemoMutationError("memo_content_too_long")


@dataclass(frozen=True)
class MemoMutationResult:
    """Normalized result returned to the Governor lifecycle owner."""

    name: str
    content: str
    record: MemoMutationRecord | None = None


@dataclass(frozen=True)
class MemoMutationExecution:
    """One governed memo execution, including durable lifecycle state."""

    operation: OperationRecord
    mutation: MemoMutationResult
    created: bool


class MemoMutationService:
    """Registered deterministic handlers for Memos mutations."""

    def __init__(self, adapter: MemoMutationAdapter) -> None:
        self._adapter = adapter
        self._handlers: dict[str, Callable[[MemoMutationCommand], MemoMutationResult]] = {
            "create": self._create,
            "edit": self._edit,
            "delete": self._delete,
        }

    @property
    def registered_operations(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def execute(self, command: MemoMutationCommand) -> MemoMutationResult:
        try:
            handler = self._handlers[command.operation_type]
        except KeyError as exc:
            raise MemoMutationError("memo_operation_not_registered") from exc
        return handler(command)

    def execute_governed(
        self,
        operations: GovernorOperations,
        command: MemoMutationCommand,
        *,
        actor: Actor,
        idempotency_key: str,
    ) -> MemoMutationExecution:
        """Execute an explicit memo action through the durable lifecycle."""

        submission = operations.submit(
            OperationRequest(
                actor=actor,
                idempotency_key=idempotency_key,
                tool_name="memos",
                operation_type=command.operation_type,
                parameters=_operation_parameters(command),
            )
        )
        operation = submission.operation
        if not submission.created:
            if operation.status != "completed":
                raise MemoMutationError(f"memo_operation_{operation.status}")
            name = str(operation.result.get("name") or command.name).strip()
            if not name:
                raise MemoMutationError("memo_operation_result_missing_name")
            return MemoMutationExecution(
                operation=operation,
                mutation=MemoMutationResult(name=name, content=command.content),
                created=False,
            )

        try:
            mutation = self.execute(command)
        except MemoMutationError as exc:
            operations.fail(operation.operation_id, error_code=exc.code)
            raise
        except Exception:
            operations.fail(operation.operation_id, error_code="memo_adapter_error")
            raise

        completed = operations.complete(operation.operation_id, result={"name": mutation.name})
        return MemoMutationExecution(operation=completed, mutation=mutation, created=True)

    def _create(self, command: MemoMutationCommand) -> MemoMutationResult:
        memo = self._adapter.create(command.content)
        name = str(memo.name or "").strip()
        if not MEMO_NAME.fullmatch(name):
            raise MemoMutationError("memo_adapter_missing_name")
        return MemoMutationResult(name=name, content=str(memo.content or ""), record=memo)

    def _edit(self, command: MemoMutationCommand) -> MemoMutationResult:
        memo = self._adapter.update(command.name, command.content)
        name = str(memo.name or "").strip()
        if name != command.name:
            raise MemoMutationError("memo_adapter_name_mismatch")
        return MemoMutationResult(name=name, content=str(memo.content or ""), record=memo)

    def _delete(self, command: MemoMutationCommand) -> MemoMutationResult:
        self._adapter.delete(command.name)
        return MemoMutationResult(name=command.name, content=command.content)


def _operation_parameters(command: MemoMutationCommand) -> dict[str, object]:
    """Return durable memo parameters without persisting memo content."""

    encoded_content = command.content.encode("utf-8")
    return {
        "name": command.name,
        "contentFingerprint": {
            "sha256": hashlib.sha256(encoded_content).hexdigest(),
            "bytes": len(encoded_content),
        },
    }
