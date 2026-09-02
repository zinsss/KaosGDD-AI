"""Strict read-only access to the pre-generated H3 maintenance report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MAINTENANCE_REPORT_PATH = Path("/data/discord-system/maintenance.json")
MAX_REPORT_BYTES = 256 * 1024
MAX_REPORT_AGE = timedelta(hours=48)
MAX_FUTURE_SKEW = timedelta(minutes=5)
TARGET_HOST = "kaosgdd"


class SystemUpdatesError(ValueError):
    """The stored update report failed the fixed read-only boundary."""


def read_system_updates(*, now: datetime | None = None) -> dict[str, Any]:
    """Read the sole fixed report path without invoking a host collector."""
    current = _utc(now or datetime.now(timezone.utc))
    try:
        content = MAINTENANCE_REPORT_PATH.read_bytes()
    except OSError as exc:
        raise SystemUpdatesError("system_updates_unavailable") from exc
    return parse_system_updates(content, now=current)


def parse_system_updates(content: bytes, *, now: datetime) -> dict[str, Any]:
    """Normalize bounded report bytes without returning arbitrary source text."""
    if not isinstance(content, bytes) or not content:
        raise SystemUpdatesError("system_updates_empty")
    if len(content) > MAX_REPORT_BYTES:
        raise SystemUpdatesError("system_updates_too_large")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemUpdatesError("system_updates_invalid_json") from exc
    if not isinstance(payload, dict):
        raise SystemUpdatesError("system_updates_invalid_payload")

    collected_at = _timestamp(payload.get("collectedAt"))
    current = _utc(now)
    age = current - collected_at
    if age < -MAX_FUTURE_SKEW:
        raise SystemUpdatesError("system_updates_future_report")
    if age > MAX_REPORT_AGE:
        raise SystemUpdatesError("system_updates_stale")

    reports = payload.get("reports")
    if not isinstance(reports, list):
        raise SystemUpdatesError("system_updates_reports_missing")
    matches = [
        item
        for item in reports
        if isinstance(item, dict)
        and isinstance(item.get("target"), dict)
        and item["target"].get("name") == TARGET_HOST
    ]
    if len(matches) != 1:
        raise SystemUpdatesError("system_updates_target_invalid")
    report = matches[0]
    if report.get("ok") is not True:
        raise SystemUpdatesError("system_updates_probe_failed")
    facts = report.get("facts")
    if not isinstance(facts, dict):
        raise SystemUpdatesError("system_updates_facts_missing")
    if facts.get("hostname") != TARGET_HOST:
        raise SystemUpdatesError("system_updates_hostname_mismatch")

    reboot_required = facts.get("reboot_required")
    if reboot_required not in {"yes", "no"}:
        raise SystemUpdatesError("system_updates_reboot_state_invalid")
    if facts.get("docker_image_updates") != "not checked; requires explicit pull":
        raise SystemUpdatesError("system_updates_image_state_invalid")

    return {
        "operation": "system.check_updates",
        "readOnly": True,
        "source": "stored-maintenance-report",
        "host": TARGET_HOST,
        "collectedAt": collected_at.isoformat().replace("+00:00", "Z"),
        "ageSeconds": max(0, int(age.total_seconds())),
        "fresh": True,
        "updates": {
            "routinePackageCount": _count(facts, "os_updates"),
            "dockerEnginePackageCount": _count(
                facts, "docker_package_updates"
            ),
            "rebootRequired": reboot_required == "yes",
            "containerImagesChecked": False,
            "containerImageStatus": "not-checked",
        },
        "containers": {
            "running": _count(facts, "docker_running"),
            "unhealthy": _count(facts, "docker_unhealthy"),
            "exited": _count(facts, "docker_exited"),
        },
    }


def _count(facts: dict[str, Any], key: str) -> int:
    value = facts.get(key)
    if isinstance(value, bool):
        raise SystemUpdatesError("system_updates_count_invalid")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise SystemUpdatesError("system_updates_count_invalid") from exc
    if count < 0 or count > 1_000_000:
        raise SystemUpdatesError("system_updates_count_invalid")
    return count


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise SystemUpdatesError("system_updates_timestamp_missing")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SystemUpdatesError("system_updates_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise SystemUpdatesError("system_updates_timestamp_invalid")
    return parsed.astimezone(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise SystemUpdatesError("system_updates_time_invalid")
    return value.astimezone(timezone.utc)
