"""Transport-neutral task normalization rules for Governor tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any


TASK_PRIORITIES = {"", "1", "5", "9"}


def validate_edit_due(due_date: str, due_time: str) -> tuple[str, str] | None:
    clean_due_date = due_date.strip()
    clean_due_time = due_time.strip()
    if not clean_due_date:
        return None if clean_due_time else ("", "")
    resolved_time = clean_due_time or "10:00"
    try:
        datetime.strptime(f"{clean_due_date} {resolved_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return clean_due_date, resolved_time


def normalize_supplies_due(payload: dict[str, Any], *, collection_id: str = "") -> dict[str, Any]:
    resolved_collection_id = collection_id or str(payload.get("collectionId") or "")
    if is_supplies_collection(resolved_collection_id):
        payload = dict(payload)
        payload["dueDate"] = ""
        payload["dueTime"] = ""
    return payload


def is_supplies_collection(collection_id: str) -> bool:
    return "supplies" in collection_id.lower()
