from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Mapping
import re

from .event_intent import EventCreateRequest
from .governor_tools import DocumentTagRequest, TaskEditRequest
from .memo_intent import MemoCreateRequest, MemoDeleteRequest, MemoEditRequest
from .task_update_intent import TaskActionRequest, TaskCreateRequest, TaskDueUpdateRequest
from .tool_intent import ToolKind, ToolRequest


class BrainGuardError(ValueError):
    """Raised when a KaosAI plan cannot safely become a Governor request."""


class BrainGuardResultKind(StrEnum):
    READONLY_TOOL = "readonly_tool"
    GOVERNOR_PROPOSAL = "governor_proposal"


@dataclass(frozen=True)
class BrainGuardContext:
    actor_id: int
    idempotency_key: str
    today: date
    default_profile: str = "main"
    supplies_collection_id: str = ""


@dataclass(frozen=True)
class BrainGuardResult:
    kind: BrainGuardResultKind
    intent: str
    request: object
    actor_id: int
    idempotency_key: str
    confirmation_required: bool


READONLY_INTENTS = {
    "today.get",
    "task.list_active",
    "task.list_completed",
    "memo.search",
    "document.search",
}

MUTATION_INTENTS = {
    "task.create",
    "task.update_due",
    "task.edit",
    "task.complete",
    "task.delete",
    "task.reopen",
    "event.create",
    "memo.create",
    "memo.edit",
    "memo.delete",
    "document.update_tags",
}

ALLOWED_INTENTS = READONLY_INTENTS | MUTATION_INTENTS
ALLOWED_SCOPES = {"personal", "family", "supplies"}
PLAN_TOP_LEVEL_KEYS = frozenset({"intent", "scope", "parameters"})
INTENT_PARAMETER_KEYS: dict[str, frozenset[str]] = {
    "today.get": frozenset({"date", "startDate"}),
    "task.list_active": frozenset(),
    "task.list_completed": frozenset({"query", "start", "end"}),
    "memo.search": frozenset({"query"}),
    "document.search": frozenset({"query"}),
    "task.create": frozenset({"title", "memo", "dueDate", "dueTime"}),
    "task.update_due": frozenset({"taskTitle", "dueDate", "dueTime"}),
    "task.edit": frozenset({"taskTitle", "title", "memo", "dueDate", "dueTime", "priority"}),
    "task.complete": frozenset({"taskTitle"}),
    "task.delete": frozenset({"taskTitle"}),
    "task.reopen": frozenset({"taskTitle"}),
    "event.create": frozenset({"title", "startDate", "endDate", "allDay", "memo"}),
    "memo.create": frozenset({"content"}),
    "memo.edit": frozenset({"query", "content"}),
    "memo.delete": frozenset({"query"}),
    "document.update_tags": frozenset({"documentId", "tags"}),
}
ACTION_BY_INTENT = {
    "task.complete": "complete",
    "task.delete": "delete",
    "task.reopen": "reopen",
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def adapt_kaosai_plan(plan: Mapping[str, Any], context: BrainGuardContext) -> BrainGuardResult:
    _reject_unknown_keys(plan, PLAN_TOP_LEVEL_KEYS, "plan")
    intent = _clean_text(plan.get("intent"))
    if intent not in ALLOWED_INTENTS:
        raise BrainGuardError("intent_not_allowed")
    parameters = _mapping(plan.get("parameters"))
    _reject_unknown_keys(parameters, INTENT_PARAMETER_KEYS[intent], f"{intent}.parameters")
    scope = _scope(plan.get("scope"), parameters)
    if intent in READONLY_INTENTS:
        request = _readonly_request(intent, parameters, scope, context)
        return BrainGuardResult(
            BrainGuardResultKind.READONLY_TOOL,
            intent,
            request,
            context.actor_id,
            context.idempotency_key,
            confirmation_required=False,
        )
    request = _mutation_request(intent, parameters, scope, context)
    return BrainGuardResult(
        BrainGuardResultKind.GOVERNOR_PROPOSAL,
        intent,
        request,
        context.actor_id,
        context.idempotency_key,
        confirmation_required=True,
    )


def _readonly_request(intent: str, parameters: Mapping[str, Any], scope: str, context: BrainGuardContext) -> ToolRequest:
    profile, collection_id = _profile_and_collection(scope, parameters, context)
    if intent == "today.get":
        start = _optional_date(parameters, "date") or _optional_date(parameters, "startDate")
        return ToolRequest(ToolKind.TODAY, start=start, profile=profile, collection_id=collection_id)
    if intent == "task.list_active":
        return ToolRequest(ToolKind.ACTIVE_TASKS, profile=profile, collection_id=collection_id)
    if intent == "task.list_completed":
        return ToolRequest(
            ToolKind.COMPLETED_TASKS,
            _clean_text(parameters.get("query")),
            _clean_text(parameters.get("start")),
            _clean_text(parameters.get("end")),
            profile,
            collection_id,
        )
    if intent == "memo.search":
        query = _required_text(parameters, "query")
        return ToolRequest(ToolKind.MEMO_SEARCH, query, profile=profile, collection_id=collection_id)
    if intent == "document.search":
        query = _required_text(parameters, "query")
        return ToolRequest(ToolKind.DOCUMENT_SEARCH, query, profile=profile, collection_id=collection_id)
    raise BrainGuardError("intent_not_allowed")


def _mutation_request(intent: str, parameters: Mapping[str, Any], scope: str, context: BrainGuardContext) -> object:
    profile, collection_id = _profile_and_collection(scope, parameters, context)
    if intent == "task.create":
        title = _required_text(parameters, "title")
        due_date = "" if scope == "supplies" else _optional_date(parameters, "dueDate")
        due_time = "" if scope == "supplies" or not due_date else _optional_time(parameters, "dueTime", default="10:00")
        return TaskCreateRequest(
            title,
            due_date,
            due_time,
            memo=_clean_text(parameters.get("memo")),
            profile=profile,
            collection_id=collection_id,
        )
    if intent == "task.update_due":
        if scope == "supplies":
            raise BrainGuardError("supplies_due_date_not_allowed")
        return TaskDueUpdateRequest(
            _required_text(parameters, "taskTitle"),
            _required_date(parameters, "dueDate"),
            _optional_time(parameters, "dueTime", default="10:00"),
            profile=profile,
            collection_id=collection_id,
        )
    if intent == "task.edit":
        due_date = "" if scope == "supplies" else _optional_date(parameters, "dueDate")
        due_time = "" if scope == "supplies" or not due_date else _optional_time(parameters, "dueTime")
        return TaskEditRequest(
            _required_text(parameters, "taskTitle"),
            _required_text(parameters, "title"),
            memo=_clean_text(parameters.get("memo")),
            due_date=due_date,
            due_time=due_time,
            priority=_clean_text(parameters.get("priority")),
            profile=profile,
            collection_id=collection_id,
        )
    if intent in ACTION_BY_INTENT:
        return TaskActionRequest(
            _required_text(parameters, "taskTitle"),
            ACTION_BY_INTENT[intent],
            profile=profile,
            collection_id=collection_id,
        )
    if intent == "event.create":
        start_date = _required_date(parameters, "startDate")
        return EventCreateRequest(
            _required_text(parameters, "title"),
            start_date,
            _optional_date(parameters, "endDate") or start_date,
            all_day=bool(parameters.get("allDay", True)),
            memo=_clean_text(parameters.get("memo")),
            profile=profile or context.default_profile,
        )
    if intent == "memo.create":
        return MemoCreateRequest(_required_content(parameters, "content"))
    if intent == "memo.edit":
        return MemoEditRequest(_required_text(parameters, "query"), _required_content(parameters, "content"))
    if intent == "memo.delete":
        return MemoDeleteRequest(_required_text(parameters, "query"))
    if intent == "document.update_tags":
        return DocumentTagRequest(_required_document_id(parameters, "documentId"), _required_tags(parameters, "tags"))
    raise BrainGuardError("intent_not_allowed")


def _scope(raw_scope: object, parameters: Mapping[str, Any]) -> str:
    scope = _clean_text(raw_scope or parameters.get("scope") or "personal").lower()
    if scope == "main":
        scope = "personal"
    if scope not in ALLOWED_SCOPES:
        raise BrainGuardError("scope_not_allowed")
    return scope


def _profile_and_collection(scope: str, parameters: Mapping[str, Any], context: BrainGuardContext) -> tuple[str, str]:
    collection_id = _clean_text(parameters.get("collectionId"))
    if scope == "family":
        return "family", collection_id
    if scope == "supplies":
        return "supplies", collection_id or context.supplies_collection_id
    return "main", collection_id


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BrainGuardError("parameters_required")
    return value


def _reject_unknown_keys(values: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(str(key) for key in values.keys() if str(key) not in allowed)
    if unknown:
        raise BrainGuardError(f"{label}_unknown_field")


def _required_text(parameters: Mapping[str, Any], key: str) -> str:
    value = _clean_text(parameters.get(key))
    if not value:
        raise BrainGuardError(f"{key}_required")
    return value


def _required_content(parameters: Mapping[str, Any], key: str) -> str:
    value = str(parameters.get(key) or "").strip()
    if not value:
        raise BrainGuardError(f"{key}_required")
    return value


def _required_document_id(parameters: Mapping[str, Any], key: str) -> str:
    value = _required_text(parameters, key)
    try:
        document_id = int(value)
    except ValueError as exc:
        raise BrainGuardError(f"{key}_invalid") from exc
    if document_id <= 0:
        raise BrainGuardError(f"{key}_invalid")
    return str(document_id)


def _required_tags(parameters: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = parameters.get(key)
    if not isinstance(raw, list | tuple):
        raise BrainGuardError(f"{key}_required")
    tags: list[str] = []
    for value in raw:
        tag = _clean_text(value).lstrip("#")
        if tag and tag not in tags:
            tags.append(tag)
    if not tags:
        raise BrainGuardError(f"{key}_required")
    return tuple(tags[:25])


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _required_date(parameters: Mapping[str, Any], key: str) -> str:
    value = _optional_date(parameters, key)
    if not value:
        raise BrainGuardError(f"{key}_required")
    return value


def _optional_date(parameters: Mapping[str, Any], key: str) -> str:
    value = _clean_text(parameters.get(key))
    if not value:
        return ""
    if not DATE_RE.fullmatch(value):
        raise BrainGuardError(f"{key}_invalid")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise BrainGuardError(f"{key}_invalid") from exc
    return value


def _optional_time(parameters: Mapping[str, Any], key: str, *, default: str = "") -> str:
    value = _clean_text(parameters.get(key)) or default
    if not value:
        return ""
    if not TIME_RE.fullmatch(value):
        raise BrainGuardError(f"{key}_invalid")
    return value
