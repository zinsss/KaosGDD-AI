from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
import threading
from typing import Any, Literal


Frequency = Literal["daily", "weekly", "monthly", "yearly"]
CreationPolicy = Literal["on_schedule", "on_completion"]
FREQUENCIES = {"daily", "weekly", "monthly", "yearly"}
CREATION_POLICIES = {"on_schedule", "on_completion"}
PRIORITIES = {"", "1", "5", "9"}
DEFAULT_TIME = "10:00"
DEFAULT_CREATION_POLICY = "on_schedule"


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
    creation_policy: CreationPolicy = DEFAULT_CREATION_POLICY
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
            "creation_policy": self.creation_policy,
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
    creation_policy = clean_text(payload.get("creationPolicy") or payload.get("creation_policy") or DEFAULT_CREATION_POLICY)
    if creation_policy not in CREATION_POLICIES:
        raise RecurringTaskError("invalid_creationPolicy")
    return {
        "owner": "family" if family_scope or payload.get("shareFamily") is True else "zin",
        "title": title,
        "memo": clean_text(payload.get("memo")),
        "first_due_date": validate_date(payload.get("firstDueDate")),
        "due_time": validate_time(payload.get("dueTime")),
        "priority": priority,
        "frequency": frequency,
        "creation_policy": creation_policy,
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
    creation_policy = clean_text(item.get("creation_policy") or DEFAULT_CREATION_POLICY)
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
        if next_due > today and (creation_policy != "on_completion" or not active_completed):
            return RecurringTaskPlan(
                action="none",
                clear_active=True,
                active_completed=active_completed,
                next_due_date=next_due,
            )
    else:
        clear_active = False
        active_completed = False

    scheduled_date = item.get("next_due_date") or item["first_due_date"]
    if scheduled_date > today and (creation_policy != "on_completion" or not clear_active or not active_completed):
        return RecurringTaskPlan(action="none")

    due_date = date_on_or_after(
        scheduled_date,
        item["frequency"],
        today=today,
        anchor=item["first_due_date"],
    )
    if due_date > today and (creation_policy != "on_completion" or not clear_active or not active_completed):
        return RecurringTaskPlan(
            action="none",
            clear_active=clear_active,
            active_completed=active_completed,
            next_due_date=due_date,
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


class PostgresRecurringTaskStore:
    def __init__(self, connect) -> None:
        self.connect = connect

    def upsert_definition(
        self,
        definition: RecurringTaskDefinition,
        *,
        now: datetime | None = None,
    ) -> RecurringTaskDefinition:
        timestamp = now or _now()
        with self.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO governor_recurring_task_definitions (
                    definition_id, owner, scope, adapter_profile, collection_id,
                    title, memo, first_due_date, due_time, priority, frequency,
                    creation_policy, enabled, active_uid, active_collection_id,
                    active_due_date, next_due_date, last_completed_uid,
                    last_completed_at, last_error, created_at, updated_at
                ) VALUES (
                    %(definition_id)s, %(owner)s, %(scope)s, %(adapter_profile)s,
                    %(collection_id)s, %(title)s, %(memo)s, %(first_due_date)s,
                    %(due_time)s, %(priority)s, %(frequency)s, %(creation_policy)s,
                    %(enabled)s, %(active_uid)s, %(active_collection_id)s,
                    %(active_due_date)s, %(next_due_date)s, %(last_completed_uid)s,
                    %(last_completed_at)s, %(last_error)s, %(created_at)s, %(updated_at)s
                )
                ON CONFLICT (definition_id) DO UPDATE SET
                    owner = EXCLUDED.owner,
                    scope = EXCLUDED.scope,
                    adapter_profile = EXCLUDED.adapter_profile,
                    collection_id = EXCLUDED.collection_id,
                    title = EXCLUDED.title,
                    memo = EXCLUDED.memo,
                    first_due_date = EXCLUDED.first_due_date,
                    due_time = EXCLUDED.due_time,
                    priority = EXCLUDED.priority,
                    frequency = EXCLUDED.frequency,
                    creation_policy = EXCLUDED.creation_policy,
                    enabled = EXCLUDED.enabled,
                    active_uid = EXCLUDED.active_uid,
                    active_collection_id = EXCLUDED.active_collection_id,
                    active_due_date = EXCLUDED.active_due_date,
                    next_due_date = EXCLUDED.next_due_date,
                    last_completed_uid = EXCLUDED.last_completed_uid,
                    last_completed_at = EXCLUDED.last_completed_at,
                    last_error = EXCLUDED.last_error,
                    updated_at = EXCLUDED.updated_at
                RETURNING definition_id, owner, scope, adapter_profile, collection_id,
                          title, memo, first_due_date, due_time, priority, frequency,
                          creation_policy, enabled, active_uid, active_collection_id,
                          active_due_date, next_due_date, last_completed_uid,
                          last_completed_at, last_error, created_at, updated_at
                """,
                _definition_parameters(definition, timestamp),
            ).fetchone()
        return _definition_from_row(row)

    def get_definition(self, definition_id: str) -> RecurringTaskDefinition:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT definition_id, owner, scope, adapter_profile, collection_id,
                       title, memo, first_due_date, due_time, priority, frequency,
                       creation_policy, enabled, active_uid, active_collection_id,
                       active_due_date, next_due_date, last_completed_uid,
                       last_completed_at, last_error, created_at, updated_at
                FROM governor_recurring_task_definitions
                WHERE definition_id = %s
                """,
                (definition_id,),
            ).fetchone()
        if not row:
            raise RecurringTaskError("recurring_task_not_found")
        return _definition_from_row(row)

    def list_definitions(self, profile: str) -> list[RecurringTaskDefinition]:
        owner = "family" if profile == "family" else "zin"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT definition_id, owner, scope, adapter_profile, collection_id,
                       title, memo, first_due_date, due_time, priority, frequency,
                       creation_policy, enabled, active_uid, active_collection_id,
                       active_due_date, next_due_date, last_completed_uid,
                       last_completed_at, last_error, created_at, updated_at
                FROM governor_recurring_task_definitions
                WHERE owner IN (%s, 'family')
                ORDER BY enabled DESC, title, definition_id
                """,
                (owner,),
            ).fetchall()
        return [_definition_from_row(row) for row in rows]

    def enabled_definitions(self) -> list[RecurringTaskDefinition]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT definition_id, owner, scope, adapter_profile, collection_id,
                       title, memo, first_due_date, due_time, priority, frequency,
                       creation_policy, enabled, active_uid, active_collection_id,
                       active_due_date, next_due_date, last_completed_uid,
                       last_completed_at, last_error, created_at, updated_at
                FROM governor_recurring_task_definitions
                WHERE enabled
                ORDER BY created_at, definition_id
                """
            ).fetchall()
        return [_definition_from_row(row) for row in rows]

    def delete_definition(self, definition_id: str) -> None:
        with self.connect() as connection:
            result = connection.execute("DELETE FROM governor_recurring_task_definitions WHERE definition_id = %s", (definition_id,))
        if result.rowcount == 0:
            raise RecurringTaskError("recurring_task_not_found")

    def clear_active_occurrence(
        self,
        definition_id: str,
        *,
        completed: bool,
        next_due_date: date,
        now: datetime | None = None,
    ) -> RecurringTaskDefinition:
        timestamp = now or _now()
        with self.connect() as connection:
            row = connection.execute(
                """
                UPDATE governor_recurring_task_definitions
                SET last_completed_uid = CASE WHEN %(completed)s THEN active_uid ELSE last_completed_uid END,
                    last_completed_at = CASE WHEN %(completed)s THEN %(updated_at)s ELSE last_completed_at END,
                    active_uid = NULL,
                    active_collection_id = NULL,
                    active_due_date = NULL,
                    next_due_date = %(next_due_date)s,
                    last_error = '',
                    updated_at = %(updated_at)s
                WHERE definition_id = %(definition_id)s
                RETURNING definition_id, owner, scope, adapter_profile, collection_id,
                          title, memo, first_due_date, due_time, priority, frequency,
                          creation_policy, enabled, active_uid, active_collection_id,
                          active_due_date, next_due_date, last_completed_uid,
                          last_completed_at, last_error, created_at, updated_at
                """,
                {
                    "definition_id": definition_id,
                    "completed": completed,
                    "next_due_date": next_due_date,
                    "updated_at": timestamp,
                },
            ).fetchone()
        if not row:
            raise RecurringTaskError("recurring_task_not_found")
        return _definition_from_row(row)

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
        with self.connect() as connection:
            row = connection.execute(
                """
                UPDATE governor_recurring_task_definitions
                SET active_uid = COALESCE(active_uid, %(uid)s),
                    active_collection_id = COALESCE(active_collection_id, %(collection_id)s),
                    active_due_date = COALESCE(active_due_date, %(due_date)s),
                    next_due_date = NULL,
                    last_error = '',
                    updated_at = %(updated_at)s
                WHERE definition_id = %(definition_id)s
                RETURNING definition_id, owner, scope, adapter_profile, collection_id,
                          title, memo, first_due_date, due_time, priority, frequency,
                          creation_policy, enabled, active_uid, active_collection_id,
                          active_due_date, next_due_date, last_completed_uid,
                          last_completed_at, last_error, created_at, updated_at
                """,
                {
                    "definition_id": definition_id,
                    "uid": uid,
                    "collection_id": collection_id,
                    "due_date": due_date,
                    "updated_at": timestamp,
                },
            ).fetchone()
        if not row:
            raise RecurringTaskError("recurring_task_not_found")
        return _definition_from_row(row)

    def record_error(
        self,
        definition_id: str,
        error: object,
        *,
        now: datetime | None = None,
    ) -> RecurringTaskDefinition:
        timestamp = now or _now()
        with self.connect() as connection:
            row = connection.execute(
                """
                UPDATE governor_recurring_task_definitions
                SET last_error = %s, updated_at = %s
                WHERE definition_id = %s
                RETURNING definition_id, owner, scope, adapter_profile, collection_id,
                          title, memo, first_due_date, due_time, priority, frequency,
                          creation_policy, enabled, active_uid, active_collection_id,
                          active_due_date, next_due_date, last_completed_uid,
                          last_completed_at, last_error, created_at, updated_at
                """,
                (clean_text(error)[:500], timestamp, definition_id),
            ).fetchone()
        if not row:
            raise RecurringTaskError("recurring_task_not_found")
        return _definition_from_row(row)


class RecurringTaskService:
    def __init__(self, store: MemoryRecurringTaskStore | PostgresRecurringTaskStore, calendar_adapter: Any) -> None:
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
        if plan.clear_active and plan.next_due_date:
            self.store.clear_active_occurrence(
                definition.definition_id,
                completed=plan.active_completed,
                next_due_date=plan.next_due_date,
                now=now,
            )
        if plan.action == "none":
            return plan
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


def _definition_parameters(definition: RecurringTaskDefinition, timestamp: datetime) -> dict[str, object]:
    return {
        "definition_id": definition.definition_id,
        "owner": definition.owner,
        "scope": definition.scope,
        "adapter_profile": definition.adapter_profile,
        "collection_id": definition.collection_id,
        "title": definition.title,
        "memo": definition.memo,
        "first_due_date": definition.first_due_date,
        "due_time": definition.due_time,
        "priority": definition.priority,
        "frequency": definition.frequency,
        "creation_policy": definition.creation_policy,
        "enabled": definition.enabled,
        "active_uid": definition.active_uid or None,
        "active_collection_id": definition.active_collection_id or None,
        "active_due_date": definition.active_due_date,
        "next_due_date": definition.next_due_date,
        "last_completed_uid": definition.last_completed_uid or None,
        "last_completed_at": definition.last_completed_at,
        "last_error": definition.last_error,
        "created_at": definition.created_at or timestamp,
        "updated_at": timestamp,
    }


def _definition_from_row(row) -> RecurringTaskDefinition:
    return RecurringTaskDefinition(
        definition_id=row[0],
        owner=row[1],
        scope=row[2],
        adapter_profile=row[3],
        collection_id=row[4],
        title=row[5],
        memo=row[6],
        first_due_date=row[7],
        due_time=row[8],
        priority=row[9],
        frequency=row[10],
        creation_policy=row[11],
        enabled=bool(row[12]),
        active_uid=row[13] or "",
        active_collection_id=row[14] or "",
        active_due_date=row[15],
        next_due_date=row[16],
        last_completed_uid=row[17] or "",
        last_completed_at=row[18],
        last_error=row[19] or "",
        created_at=row[20],
        updated_at=row[21],
    )
