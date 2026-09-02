"""Strict read-only adapter for the pre-generated H3 maintenance report."""

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


class MaintenanceReportError(ValueError):
    """The stored report failed the fixed read-only boundary."""


class StoredMaintenanceReportAdapter:
    """Read a bounded stored report without invoking a host collector."""

    def read(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = self._utc(now or datetime.now(timezone.utc))
        try:
            content = MAINTENANCE_REPORT_PATH.read_bytes()
        except OSError as exc:
            raise MaintenanceReportError("maintenance report is unavailable") from exc
        return self.parse(content, now=current)

    @staticmethod
    def parse(content: bytes, *, now: datetime) -> dict[str, Any]:
        """Parse bounded report bytes; exposed separately for deterministic tests."""
        if not isinstance(content, bytes) or not content:
            raise MaintenanceReportError("maintenance report is empty")
        if len(content) > MAX_REPORT_BYTES:
            raise MaintenanceReportError("maintenance report exceeds the size limit")
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MaintenanceReportError("maintenance report is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MaintenanceReportError("maintenance report must be an object")

        collected_at = StoredMaintenanceReportAdapter._timestamp(
            payload.get("collectedAt")
        )
        current = StoredMaintenanceReportAdapter._utc(now)
        age = current - collected_at
        if age < -MAX_FUTURE_SKEW:
            raise MaintenanceReportError("maintenance report timestamp is in the future")
        if age > MAX_REPORT_AGE:
            raise MaintenanceReportError("maintenance report is stale")

        reports = payload.get("reports")
        if not isinstance(reports, list):
            raise MaintenanceReportError("maintenance report entries are missing")
        matches = [
            item
            for item in reports
            if isinstance(item, dict)
            and isinstance(item.get("target"), dict)
            and item["target"].get("name") == TARGET_HOST
        ]
        if len(matches) != 1:
            raise MaintenanceReportError(
                "maintenance report must contain exactly one allowlisted H3 target"
            )
        report = matches[0]
        if report.get("ok") is not True:
            raise MaintenanceReportError("allowlisted H3 maintenance probe failed")
        facts = report.get("facts")
        if not isinstance(facts, dict):
            raise MaintenanceReportError("allowlisted H3 maintenance facts are missing")
        if facts.get("hostname") != TARGET_HOST:
            raise MaintenanceReportError("maintenance hostname does not match the target")

        reboot_required = facts.get("reboot_required")
        if reboot_required not in {"yes", "no"}:
            raise MaintenanceReportError("reboot-required state is invalid")
        image_update_state = facts.get("docker_image_updates")
        if image_update_state != "not checked; requires explicit pull":
            raise MaintenanceReportError("container image update state is missing")

        return {
            "operation": "system.check_updates",
            "readOnly": True,
            "source": "stored-maintenance-report",
            "host": TARGET_HOST,
            "collectedAt": collected_at.isoformat().replace("+00:00", "Z"),
            "ageSeconds": max(0, int(age.total_seconds())),
            "fresh": True,
            "updates": {
                "routinePackageCount": StoredMaintenanceReportAdapter._count(
                    facts, "os_updates"
                ),
                "dockerEnginePackageCount": StoredMaintenanceReportAdapter._count(
                    facts, "docker_package_updates"
                ),
                "rebootRequired": reboot_required == "yes",
                "containerImagesChecked": False,
                "containerImageStatus": "not-checked",
            },
            "containers": {
                "running": StoredMaintenanceReportAdapter._count(
                    facts, "docker_running"
                ),
                "unhealthy": StoredMaintenanceReportAdapter._count(
                    facts, "docker_unhealthy"
                ),
                "exited": StoredMaintenanceReportAdapter._count(
                    facts, "docker_exited"
                ),
            },
        }

    @staticmethod
    def _count(facts: dict[str, Any], key: str) -> int:
        value = facts.get(key)
        if isinstance(value, bool):
            raise MaintenanceReportError(f"maintenance count is invalid: {key}")
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise MaintenanceReportError(f"maintenance count is invalid: {key}") from exc
        if count < 0 or count > 1_000_000:
            raise MaintenanceReportError(f"maintenance count is out of range: {key}")
        return count

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if not isinstance(value, str) or not value:
            raise MaintenanceReportError("maintenance report timestamp is missing")
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise MaintenanceReportError("maintenance report timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise MaintenanceReportError("maintenance report timestamp lacks timezone")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise MaintenanceReportError("current time lacks timezone")
        return value.astimezone(timezone.utc)
