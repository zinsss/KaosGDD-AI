"""Deterministic task mutation handlers owned by KaosGovernor.

The transport is responsible for authentication, actor construction, and
presentation. This module owns the final mapping from a validated task
operation to the authoritative calendar adapter call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


TASK_PROFILES = frozenset({"main", "family", "supplies"})
TASK_OPERATION_TYPES = frozenset(
    {
        "create",
        "update_due",
        "edit",
        "complete",
        "reopen",
        "delete",
    }
)


class TaskMutationError(ValueError):
    """A deterministic task command failed Governor validation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TaskMutationAdapter(Protocol):
    """Narrow authoritative adapter contract used by task handlers."""

    def create_task(self, profile: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def update_task(self, profile: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def delete_task(self, profile: str, uid: str, collection_id: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class TaskMutationCommand:
    """A normalized task mutation ready for deterministic execution."""

    operation_type: str
    profile: str
    payload: Mapping[str, Any]
    uid: str = ""
    collection_id: str = ""

    def __post_init__(self) -> None:
        if self.operation_type not in TASK_OPERATION_TYPES:
            raise TaskMutationError("task_operation_not_registered")
        if self.profile not in TASK_PROFILES:
            raise TaskMutationError("task_profile_invalid")
        if not isinstance(self.payload, Mapping):
            raise TaskMutationError("task_payload_invalid")

        payload_uid = str(self.payload.get("uid") or "").strip()
        if self.operation_type == "create":
            if not str(self.payload.get("title") or "").strip():
                raise TaskMutationError("task_title_required")
        elif not self.uid.strip():
            raise TaskMutationError("task_uid_required")
        elif self.operation_type != "delete" and payload_uid != self.uid.strip():
            raise TaskMutationError("task_uid_mismatch")

        resolved_collection = self.collection_id or str(self.payload.get("collectionId") or "")
        if self.profile == "supplies" or "supplies" in resolved_collection.lower():
            if any(str(self.payload.get(key) or "").strip() for key in ("dueDate", "dueTime")):
                raise TaskMutationError("supplies_schedule_not_allowed")


@dataclass(frozen=True)
class TaskMutationResult:
    """Normalized result returned to the Governor lifecycle owner."""

    uid: str
    adapter_result: Mapping[str, Any]


class TaskMutationService:
    """Registered deterministic handlers for task and supply mutations."""

    def __init__(self, adapter: TaskMutationAdapter) -> None:
        self._adapter = adapter
        self._handlers: dict[str, Callable[[TaskMutationCommand], TaskMutationResult]] = {
            "create": self._create,
            "update_due": self._update,
            "edit": self._update,
            "complete": self._update,
            "reopen": self._update,
            "delete": self._delete,
        }

    @property
    def registered_operations(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def execute(self, command: TaskMutationCommand) -> TaskMutationResult:
        try:
            handler = self._handlers[command.operation_type]
        except KeyError as exc:
            raise TaskMutationError("task_operation_not_registered") from exc
        return handler(command)

    def _create(self, command: TaskMutationCommand) -> TaskMutationResult:
        result = dict(self._adapter.create_task(command.profile, dict(command.payload)))
        uid = str(result.get("uid") or "").strip()
        if not uid:
            raise TaskMutationError("task_adapter_missing_uid")
        return TaskMutationResult(uid=uid, adapter_result=result)

    def _update(self, command: TaskMutationCommand) -> TaskMutationResult:
        result = dict(self._adapter.update_task(command.profile, dict(command.payload)))
        uid = str(result.get("uid") or command.uid).strip()
        if uid != command.uid:
            raise TaskMutationError("task_adapter_uid_mismatch")
        return TaskMutationResult(uid=uid, adapter_result=result)

    def _delete(self, command: TaskMutationCommand) -> TaskMutationResult:
        result = dict(
            self._adapter.delete_task(
                command.profile,
                command.uid,
                command.collection_id,
            )
        )
        result_uid = str(result.get("uid") or command.uid).strip()
        if result_uid != command.uid:
            raise TaskMutationError("task_adapter_uid_mismatch")
        return TaskMutationResult(uid=result_uid, adapter_result=result)
