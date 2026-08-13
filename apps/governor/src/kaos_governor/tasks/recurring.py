from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
import threading
from typing import Any, Literal


Frequency = Literal["daily", "weekly", "monthly", "yearly"]
FREQUENCIES = {"daily", "weekly", "monthly", "yearly"}
PRIORITIES = {"", "1", "5", "9"}
DEFAULT_TIME = "10:00"


class RecurringTaskError(ValueError):
    pass


@dataclass(frozen=True)
class RecurringTaskPlan:
    action: Literal["none", "adopt", "create"]
    due_date: date | None = None
    uid: str = ""
    clear_active: bool = False
    active_completed: bool = False
    next_due_date: date | None = None


@dataclass(frozen=True)
class RecurringTaskDefinition:
    definition_id: str
    owner: str
    scope: Literal["personal", "family"]
    adapter_profile: Literal["main", "family"]
    collection_id: str
    title: str
    memo: str
    first_due_date: date
    due_time: time
    priority: str
    frequency: Frequency
    enabled: bool = True
    active_uid: str = ""
    active_collection_id: str = ""
    active_due_date: date | None = None
    next_due_date: date | None = None
    last_completed_uid: str = ""
    last_completed_at: datetime | None = None
    last_error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def as_planner_mapping(self) -> dict[str, object]:
        return {
            "id": self.definition_id,
            "owner": self.owner,
            "collection_id": self.collection_id,
            "title": self.title,
            "memo": self.memo,
            "first_due_date": self.first_due_date,
            "due_time": self.due_time,
            "priority": self.priority,
            "frequency": self.frequency,
            "active_uid": self.active_uid or None,
            "active_collection_id": self.active_collection_id or None,
            "active_due_date": self.active_due_date,
            "next_due_date": self.next_due_date,
        }


def clean_text(value: object) -> str:
    return str(value or "").strip()


def validate_date(value: object, field: str = "firstDueDate") -> date:
    try:
        return date.fromisoformat(clean_text(value))
    except ValueError as exc:
        raise RecurringTaskError(f"invalid_{field}") from exc


def validate_time(value: object) -> time:
    raw = clean_text(value) or DEFAULT_TIME
    try:
        parsed = datetime.strptime(raw, "%H:%M").time()
    except ValueError as exc:
        raise RecurringTaskError("invalid_dueTime") from exc
    if parsed.minute % 5:
        raise RecurringTaskError("invalid_dueTime_step")
    return parsed


def validate_payload(payload: Mapping[str, Any], *, family_scope: bool = False) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise RecurringTaskError("invalid_payload")
    title = " ".join(clean_text(payload.get("title")).split())
    if not title:
        raise RecurringTaskError("title_required")
    frequency = clean_text(payload.get("frequency")).lower()
    if frequency not in FREQUENCIES:
        raise RecurringTaskError("invalid_frequency")
    priority = clean_text(payload.get("priority"))
    if priority not in PRIORITIES:
        raise RecurringTaskError("invalid_priority")
    return {
        "owner": "family" if family_scope or payload.get("shareFamily") is True else "zin",
        "title": title,
        "memo": clean_text(payload.get("memo")),
        "first_due_date": validate_date(payload.get("firstDueDate")),
        "due_time": validate_time(payload.get("dueTime")),
        "priority": priority,
        "frequency": frequency,
        "enabled": payload.get("enabled") is not False,
    }


def add_months(value: date, months: int, preferred_day: int | None = None) -> date:
    target_month = value.month - 1 + months
    year = value.year + target_month // 12
    month = target_month % 12 + 1
    day = min(preferred_day or value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_scheduled_date(value: date, frequency: str, *, anchor: date | None = None) -> date:
    anchor_date = anchor or value
    if frequency == "daily":
        return value + timedelta(days=1)
    if frequency == "weekly":
        return value + timedelta(days=7)
    if frequency == "monthly":
        return add_months(value, 1, anchor_date.day)
    if frequency == "yearly":
        target_year = value.year + 1
        target_day = min(anchor_date.day, calendar.monthrange(target_year, anchor_date.month)[1])
        return date(target_year, anchor_date.month, target_day)
    raise RecurringTaskError("invalid_frequency")


def date_on_or_after(value: date, frequency: str, *, today: date, anchor: date | None = None) -> date:
    candidate = value
    while candidate < today:
        candidate = next_scheduled_date(candidate, frequency, anchor=anchor)
    return candidate


def next_current_date(value: date, frequency: str, *, today: date, anchor: date | None = None) -> date:
    return date_on_or_after(
        next_scheduled_date(value, frequency, anchor=anchor),
        frequency,
        today=today,
        anchor=anchor,
    )


def occurrence_uid(definition: Mapping[str, Any] | RecurringTaskDefinition, due_date: date) -> str:
    if isinstance(definition, RecurringTaskDefinition):
        definition = definition.as_planner_mapping()
    definition_id = "".join(character for character in clean_text(definition.get("id")).upper() if character.isalnum())
    return f"KAOSGDD-REPEAT-{definition_id}-{due_date.strftime('%Y%m%d')}"


def _task_matches_active(definition: Mapping[str, Any], task: Mapping[str, Any]) -> bool:
    active_collection_id = definition.get("active_collection_id")
    return (
        task.get("uid") == definition.get("active_uid")
        and (not active_collection_id or task.get("collection") == active_collection_id)
    )


def _is_completed(task: Mapping[str, Any] | None) -> bool:
    return str((task or {}).get("status") or "NEEDS-ACTION").upper() == "COMPLETED"


def _existing_occurrence(tasks: Iterable[Mapping[str, Any]], uid: str, collection_id: object) -> Mapping[str, Any] | None:
    return next((task for task in tasks if task.get("uid") == uid and task.get("collection") == collection_id), None)


def plan_synchronization(
    definition: Mapping[str, Any] | RecurringTaskDefinition,
    tasks: Iterable[Mapping[str, Any]],
    *,
    today: date,
) -> RecurringTaskPlan:
    task_items = list(tasks)
    item = definition.as_planner_mapping() if isinstance(definition, RecurringTaskDefinition) else dict(definition)
    active_uid = item.get("active_uid")
    if active_uid:
        active = next((task for task in task_items if _task_matches_active(item, task)), None)
        if active and not _is_completed(active):
            return RecurringTaskPlan(action="none")
        next_due = next_current_date(
            item["active_due_date"],
            item["frequency"],
            today=today,
            anchor=item["first_due_date"],
        )
        item.update(
            {
                "active_uid": None,
                "active_collection_id": None,
                "active_due_date": None,
                "next_due_date": next_due,
            }
        )
        clear_active = True
        active_completed = bool(active)
    else:
        clear_active = False
        active_completed = False

    due_date = date_on_or_after(
        item.get("next_due_date") or item["first_due_date"],
        item["frequency"],
        today=today,
        anchor=item["first_due_date"],
    )
    uid = occurrence_uid(item, due_date)
    if _existing_occurrence(task_items, uid, item["collection_id"]):
        return RecurringTaskPlan(
            action="adopt",
            due_date=due_date,
            uid=uid,
            clear_active=clear_active,
            active_completed=active_completed,
            next_due_date=due_date,
        )
    return RecurringTaskPlan(
        action="create",
        due_date=due_date,
        uid=uid,
        clear_active=clear_active,
        active_completed=active_completed,
        next_due_date=due_date,
    )


class MemoryRecurringTaskStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._definitions: dict[str, RecurringTaskDefinition] = {}

    def upsert_definition(
        self,
        definition: RecurringTaskDefinition,
        *,
        now: datetime | None = None,
    ) -> RecurringTaskDefinition:
        timestamp = now or _now()
        with self._lock:
            current = self._definitions.get(definition.definition_id)
            stored = replace(
                definition,
                created_at=current.created_at if current else timestamp,
                updated_at=timestamp,
            )
            self._definitions[definition.definition_id] = stored
            return stored

    def get_definition(self, definition_id: str) -> RecurringTaskDefinition:
        with self._lock:
            try:
                return self._definitions[definition_id]
            except KeyError as exc:
                raise RecurringTaskError("recurring_task_not_found") from exc

    def delete_definition(self, definition_id: str) -> None:
        with self._lock:
            if definition_id not in self._definitions:
                raise RecurringTaskError("recurring_task_not_found")
            del self._definitions[definition_id]

    def enabled_definitions(self) -> list[RecurringTaskDefinition]:
        with self._lock:
            return [
                item
                for item in sorted(self._definitions.values(), key=lambda value: (value.created_at or _now(), value.definition_id))
                if item.enabled
            ]

    def clear_active_occurrence(
        self,
        definition_id: str,
        *,
        completed: bool,
        next_due_date: date,
        now: datetime | None = None,
    ) -> RecurringTaskDefinition:
        timestamp = now or _now()
        with self._lock:
            current = self.get_definition(definition_id)
            updated = replace(
                current,
                active_uid="",
                active_collection_id="",
                active_due_date=None,
                next_due_date=next_due_date,
                last_completed_uid=current.active_uid if completed else current.last_completed_uid,
                last_completed_at=timestamp if completed else current.last_completed_at,
                last_error="",
                updated_at=timestamp,
            )
            self._definitions[definition_id] = updated
            return updated

    def assign_active_occurrence(
        self,
        definition_id: str,
        *,
        uid: str,
        collection_id: str,
        due_date: date,
        now: datetime | None = None,
    ) -> RecurringTaskDefinition:
        timestamp = now or _now()
        with self._lock:
            current = self.get_definition(definition_id)
            if current.active_uid:
                return current
            updated = replace(
                current,
                active_uid=uid,
                active_collection_id=collection_id,
                active_due_date=due_date,
                next_due_date=None,
                last_error="",
                updated_at=timestamp,
            )
            self._definitions[definition_id] = updated
            return updated

    def record_error(
        self,
        definition_id: str,
        error: object,
        *,
        now: datetime | None = None,
    ) -> RecurringTaskDefinition:
        timestamp = now or _now()
        with self._lock:
            current = self.get_definition(definition_id)
            updated = replace(current, last_error=clean_text(error)[:500], updated_at=timestamp)
            self._definitions[definition_id] = updated
            return updated


class RecurringTaskService:
    def __init__(self, store: MemoryRecurringTaskStore, calendar_adapter: Any) -> None:
        self.store = store
        self.calendar_adapter = calendar_adapter

    def synchronize_definition(
        self,
        definition: RecurringTaskDefinition,
        *,
        today: date,
        now: datetime | None = None,
    ) -> RecurringTaskPlan:
        tasks = self.calendar_adapter.list_tasks(definition.adapter_profile)
        plan = plan_synchronization(definition.as_planner_mapping(), tasks, today=today)
        if plan.action == "none":
            return plan
        if plan.clear_active and plan.next_due_date:
            self.store.clear_active_occurrence(
                definition.definition_id,
                completed=plan.active_completed,
                next_due_date=plan.next_due_date,
                now=now,
            )
        if plan.action == "adopt":
            self.store.assign_active_occurrence(
                definition.definition_id,
                uid=plan.uid,
                collection_id=definition.collection_id,
                due_date=_require_due_date(plan),
                now=now,
            )
            return plan
        result = self.calendar_adapter.create_task(
            definition.adapter_profile,
            {
                "uid": plan.uid,
                "collectionId": definition.collection_id,
                "title": definition.title,
                "memo": definition.memo,
                "dueDate": _require_due_date(plan).isoformat(),
                "dueTime": definition.due_time.strftime("%H:%M"),
                "priority": definition.priority,
            },
        )
        uid = clean_text(result.get("uid")) or plan.uid
        collection_id = clean_text(result.get("collection")) or definition.collection_id
        self.store.assign_active_occurrence(
            definition.definition_id,
            uid=uid,
            collection_id=collection_id,
            due_date=_require_due_date(plan),
            now=now,
        )
        return plan

    def run_once(self, *, today: date, now: datetime | None = None) -> list[tuple[str, RecurringTaskPlan]]:
        results = []
        for definition in self.store.enabled_definitions():
            try:
                plan = self.synchronize_definition(definition, today=today, now=now)
                results.append((definition.definition_id, plan))
            except Exception as exc:
                self.store.record_error(definition.definition_id, str(exc) or type(exc).__name__, now=now)
                results.append((definition.definition_id, RecurringTaskPlan(action="none")))
        return results


def _now() -> datetime:
    return datetime.now(UTC)


def _require_due_date(plan: RecurringTaskPlan) -> date:
    if plan.due_date is None:
        raise RecurringTaskError("recurring_task_plan_missing_due_date")
    return plan.due_date
