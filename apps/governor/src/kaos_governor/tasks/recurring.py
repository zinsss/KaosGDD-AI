from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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


def occurrence_uid(definition: Mapping[str, Any], due_date: date) -> str:
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
    definition: Mapping[str, Any],
    tasks: Iterable[Mapping[str, Any]],
    *,
    today: date,
) -> RecurringTaskPlan:
    task_items = list(tasks)
    item = dict(definition)
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
