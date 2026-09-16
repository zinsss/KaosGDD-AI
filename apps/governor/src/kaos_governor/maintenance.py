"""Transport-neutral maintenance report parsing and reminder scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from .notifications import TextNotification, TextNotificationService


KST = timezone(timedelta(hours=9), "KST")
DEFAULT_REPORT_PATH = Path("/data/notifications/maintenance-report.json")
DEFAULT_REPORT_MAX_AGE = timedelta(days=2)
MAX_REPORT_BYTES = 256 * 1024
OPENCLAW_AUTH_STATUSES = frozenset(("ok", "expiring", "expired", "missing", "static"))


class MaintenanceConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class MaintenanceTarget:
    name: str
    mode: str
    address: str
    repo_path: str = ""


@dataclass(frozen=True)
class MaintenanceReport:
    target: MaintenanceTarget
    ok: bool
    facts: Mapping[str, str]
    error: str = ""
    collected_at: str = ""


@dataclass(frozen=True)
class OpenClawRenewalReminder:
    key: str
    target: str
    model: str
    auth_status: str
    expires_at: str
    reminder_on: date
    expires_on: date | None
    estimated: bool = False


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise MaintenanceConfigurationError(f"{name} must be true or false")


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise MaintenanceConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise MaintenanceConfigurationError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class MaintenanceReminderConfig:
    enabled: bool = True
    report_path: Path = DEFAULT_REPORT_PATH
    state_path: Path = Path("/data/notifications/maintenance-reminders.json")
    poll_seconds: int = 3600
    max_report_age_seconds: int = int(DEFAULT_REPORT_MAX_AGE.total_seconds())

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "MaintenanceReminderConfig":
        source = os.environ if env is None else env
        return cls(
            enabled=_bool(source, "SYSTEM_MAINTENANCE_REMINDERS_ENABLED", True),
            report_path=Path(
                source.get("SYSTEM_MAINTENANCE_REPORT_PATH", "").strip()
                or DEFAULT_REPORT_PATH
            ),
            state_path=Path(
                source.get("SYSTEM_MAINTENANCE_REMINDER_STATE_PATH", "").strip()
                or "/data/notifications/maintenance-reminders.json"
            ),
            poll_seconds=_positive_int(
                source,
                "SYSTEM_MAINTENANCE_REMINDER_POLL_SECONDS",
                3600,
            ),
            max_report_age_seconds=_positive_int(
                source,
                "SYSTEM_MAINTENANCE_REPORT_MAX_AGE_SECONDS",
                int(DEFAULT_REPORT_MAX_AGE.total_seconds()),
            ),
        )


def _error_report(path: Path, error: str) -> list[MaintenanceReport]:
    return [
        MaintenanceReport(
            MaintenanceTarget("maintenance", "file", "", str(path)),
            False,
            {},
            error,
        )
    ]


def load_stored_maintenance_reports(path: Path) -> list[MaintenanceReport]:
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return _error_report(path, "maintenance report unavailable")
    except OSError as exc:
        return _error_report(path, stable_error(exc))
    if not content:
        return _error_report(path, "maintenance report empty")
    if len(content) > MAX_REPORT_BYTES:
        return _error_report(path, "maintenance report too large")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_report(path, "maintenance report invalid")
    if not isinstance(payload, dict):
        return _error_report(path, "maintenance report invalid")
    collected_at = str(payload.get("collectedAt") or "")
    reports: list[MaintenanceReport] = []
    items = payload.get("reports")
    if not isinstance(items, list):
        return _error_report(path, "maintenance report invalid")
    for item in items:
        if not isinstance(item, dict):
            continue
        target_payload = item.get("target")
        if not isinstance(target_payload, dict):
            target_payload = {}
        facts_payload = item.get("facts")
        if not isinstance(facts_payload, dict):
            facts_payload = {}
        target = MaintenanceTarget(
            str(target_payload.get("name") or item.get("name") or "unknown"),
            str(target_payload.get("mode") or ""),
            str(target_payload.get("address") or ""),
            str(target_payload.get("repoPath") or ""),
        )
        facts = {
            str(key): str(value)
            for key, value in facts_payload.items()
            if str(key)
        }
        reports.append(
            MaintenanceReport(
                target,
                item.get("ok") is True,
                facts,
                str(item.get("error") or ""),
                str(item.get("collectedAt") or collected_at),
            )
        )
    return reports or _error_report(path, "maintenance report empty")


def _maintenance_report_time(report: MaintenanceReport) -> datetime | None:
    value = str(report.collected_at or report.facts.get("checked_at") or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def report_is_fresh(
    report: MaintenanceReport,
    *,
    now: datetime,
    max_age: timedelta,
) -> bool:
    checked_at = _maintenance_report_time(report)
    if checked_at is None:
        return False
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    age = current.astimezone(timezone.utc) - checked_at
    return timedelta(0) <= age <= max_age


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def maintenance_issues(
    reports: list[MaintenanceReport],
    *,
    now: datetime,
    max_age: timedelta,
) -> tuple[str, ...]:
    issues: list[str] = []
    for report in reports:
        if not report_is_fresh(report, now=now, max_age=max_age):
            continue
        target = report.target.name
        if not report.ok:
            issues.append(f"{target}: check failed")
            continue
        facts = report.facts
        if facts.get("reboot_required", "").strip().lower() == "yes":
            issues.append(f"{target}: reboot required")
        for key, label in (
            ("os_updates", "OS updates"),
            ("docker_package_updates", "Docker package updates"),
            ("docker_unhealthy", "unhealthy containers"),
        ):
            count = _nonnegative_int(facts.get(key, ""))
            if count > 0:
                issues.append(f"{target}: {count} {label}")
    return tuple(issues)


def _openclaw_auth_status(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in OPENCLAW_AUTH_STATUSES else "unknown"


def parse_openclaw_expiry(value: object) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        if numeric < 100_000_000_000:
            numeric *= 1000
        try:
            return datetime.fromtimestamp(numeric / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.lower() == "unknown":
        return None
    try:
        return parse_openclaw_expiry(float(text))
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_openclaw_expiry(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _openclaw_report_date(report: MaintenanceReport) -> date:
    checked_at = _maintenance_report_time(report)
    return (checked_at or datetime.now(timezone.utc)).astimezone(KST).date()


def parse_openclaw_timestamp_date(value: str) -> date | None:
    text = value.strip()
    if not text or text == "unknown":
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST)
    return parsed.date()


def openclaw_renewal_from_report(
    report: MaintenanceReport,
) -> OpenClawRenewalReminder | None:
    facts = report.facts
    if not report.ok or facts.get("openclaw_configured") != "yes":
        return None
    model = str(facts.get("openclaw_primary_model") or "unknown")
    if "openclaw_auth_status" in facts:
        auth_status = _openclaw_auth_status(facts.get("openclaw_auth_status"))
        expires_at = parse_openclaw_expiry(facts.get("openclaw_auth_expires_at"))
        if auth_status in {"unknown", "static"}:
            return None
        if auth_status == "ok" and expires_at is None:
            return None
        observed_on = _openclaw_report_date(report)
        expires_on = expires_at.astimezone(KST).date() if expires_at else None
        reminder_on = (
            observed_on
            if auth_status in {"missing", "expired"}
            else (expires_on - timedelta(days=1) if expires_on else observed_on)
        )
        expires_text = _format_openclaw_expiry(expires_at) if expires_at else ""
        key_suffix = expires_text or f"{auth_status}:{observed_on.isoformat()}"
        return OpenClawRenewalReminder(
            key=f"openclaw-chatgpt:{report.target.name}:{key_suffix}",
            target=report.target.name,
            model=model,
            auth_status=auth_status,
            expires_at=expires_text,
            reminder_on=reminder_on,
            expires_on=expires_on,
        )

    last_touched_date = parse_openclaw_timestamp_date(
        str(facts.get("openclaw_last_touched") or "")
    )
    if last_touched_date is None:
        return None
    expires_on = last_touched_date + timedelta(days=10)
    reminder_on = last_touched_date + timedelta(days=9)
    return OpenClawRenewalReminder(
        key=(
            f"openclaw-chatgpt:{report.target.name}:"
            f"{last_touched_date.isoformat()}:{reminder_on.isoformat()}"
        ),
        target=report.target.name,
        model=model,
        auth_status="estimated",
        expires_at=expires_on.isoformat(),
        reminder_on=reminder_on,
        expires_on=expires_on,
        estimated=True,
    )


def due_openclaw_renewal_reminders(
    reports: list[MaintenanceReport],
    *,
    now: datetime,
    max_age: timedelta,
) -> list[OpenClawRenewalReminder]:
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    today = current.astimezone(KST).date()
    reminders: list[OpenClawRenewalReminder] = []
    for report in reports:
        if not report_is_fresh(report, now=current, max_age=max_age):
            continue
        reminder = openclaw_renewal_from_report(report)
        if reminder is not None and today >= reminder.reminder_on:
            reminders.append(reminder)
    return reminders


def _auth_message(reminder: OpenClawRenewalReminder) -> str:
    if reminder.auth_status == "missing":
        state = "is missing"
    elif reminder.auth_status == "expired":
        state = "has expired"
    elif reminder.expires_on is not None:
        state = f"expires on {reminder.expires_on.isoformat()}"
    else:
        state = "needs renewal"
    return f"KaosBrain ChatGPT authentication {state}. Reauthorize in AI Tasks."


class MaintenanceReminderService:
    """Read host-generated reports and enqueue transport-neutral alerts."""

    def __init__(
        self,
        config: MaintenanceReminderConfig,
        notifications: TextNotificationService,
    ) -> None:
        self.config = config
        self.notifications = notifications
        self._next_check_at: datetime | None = None
        self._last_check_at = ""
        self._last_report_at = ""
        self._last_actionable_count = 0
        self._last_scheduled_count = 0
        self._last_error = ""

    @staticmethod
    def _current_utc(now: datetime | None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def run_due(self, now: datetime | None = None) -> int:
        if not self.config.enabled:
            return 0
        current = self._current_utc(now)
        if self._next_check_at is not None and current < self._next_check_at:
            return 0
        self._next_check_at = current + timedelta(seconds=self.config.poll_seconds)
        reports = load_stored_maintenance_reports(self.config.report_path)
        max_age = timedelta(seconds=self.config.max_report_age_seconds)
        issues = maintenance_issues(reports, now=current, max_age=max_age)
        renewals = due_openclaw_renewal_reminders(
            reports,
            now=current,
            max_age=max_age,
        )
        notifications: list[tuple[str, TextNotification]] = []
        if issues:
            digest = hashlib.sha256("\0".join(issues).encode("utf-8")).hexdigest()[:20]
            notifications.append(
                (
                    f"system-maintenance:{digest}",
                    TextNotification(
                        key=f"maintenance:system-maintenance:{digest}",
                        category="maintenance",
                        title="System maintenance",
                        message="; ".join(issues),
                        priority=1,
                    ),
                )
            )
        notifications.extend(
            (
                reminder.key,
                TextNotification(
                    key=f"maintenance:{reminder.key}",
                    category="maintenance",
                    title="KaosBrain auth renewal",
                    message=_auth_message(reminder),
                    priority=1,
                ),
            )
            for reminder in renewals
        )
        sent_keys = self._load_sent_keys()
        scheduled = 0
        state_changed = False
        for state_key, notification in notifications:
            if state_key in sent_keys:
                continue
            scheduled += int(self.notifications.enqueue(notification))
            sent_keys.add(state_key)
            state_changed = True
        if state_changed:
            self._save_sent_keys(sent_keys)
        report_times = [
            report.collected_at for report in reports if report.collected_at
        ]
        self._last_check_at = current.isoformat().replace("+00:00", "Z")
        self._last_report_at = max(report_times, default="")
        self._last_actionable_count = len(notifications)
        self._last_scheduled_count = scheduled
        errors = [report.error for report in reports if not report.ok and report.error]
        self._last_error = "; ".join(errors)[:500]
        return scheduled

    def _load_sent_keys(self) -> set[str]:
        try:
            payload = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return set()
        if not isinstance(payload, dict) or not isinstance(payload.get("sent"), list):
            return set()
        return {str(item) for item in payload["sent"] if str(item)}

    def _save_sent_keys(self, sent_keys: set[str]) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.state_path.with_name(f".{self.config.state_path.name}.tmp")
        temporary.write_text(
            json.dumps({"sent": sorted(sent_keys)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.config.state_path)

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "pollSeconds": self.config.poll_seconds,
            "lastCheckAt": self._last_check_at,
            "lastReportAt": self._last_report_at,
            "lastActionableCount": self._last_actionable_count,
            "lastScheduledCount": self._last_scheduled_count,
            "lastError": self._last_error,
        }


def stable_error(exc: BaseException) -> str:
    return str(exc)[:200] or exc.__class__.__name__
