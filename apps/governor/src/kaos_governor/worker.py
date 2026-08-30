from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
from typing import Mapping

from .calendar import CalendarAdapterClient, CalendarAdapterConfig
from .daily_digest import DailyDigestConfig, DailyDigestService, KST, digest_events
from .fax import FaxConfig, FaxService
from .import_workers import (
    FaxLifecycleWorker,
    ImportCycleResult,
    NaverMailLifecycleWorker,
)
from .mail import NaverMailConfig, NaverMailPoller
from .notifications import PushoverConfig, TextNotification, TextNotificationService


LOGGER = logging.getLogger(__name__)


class WorkerConfigurationError(ValueError):
    pass


class WorkerCycleError(RuntimeError):
    pass


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise WorkerConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise WorkerConfigurationError(f"{name} must be positive")
    return value


def _timestamp(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@dataclass(frozen=True)
class WorkerConfig:
    status_path: Path = Path("/data/notifications/governor-worker.json")
    health_stale_seconds: int = 60
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        poll_seconds: int = 10,
    ) -> "WorkerConfig":
        source = os.environ if env is None else env
        return cls(
            status_path=Path(
                source.get(
                    "GOVERNOR_WORKER_STATE_PATH",
                    "/data/notifications/governor-worker.json",
                )
            ),
            health_stale_seconds=_positive_int(
                source,
                "GOVERNOR_WORKER_HEALTH_STALE_SECONDS",
                max(60, poll_seconds * 4),
            ),
            log_level=source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )


class GovernorWorker:
    def __init__(
        self,
        config: WorkerConfig,
        notifications: TextNotificationService,
        daily_digest: DailyDigestService | None = None,
        mail_lifecycle: NaverMailLifecycleWorker | None = None,
        fax_lifecycle: FaxLifecycleWorker | None = None,
    ) -> None:
        self.config = config
        self.notifications = notifications
        self.daily_digest = daily_digest
        self.mail_lifecycle = mail_lifecycle
        self.fax_lifecycle = fax_lifecycle
        self._next_digest_check_at: datetime | None = None
        self._next_content_refresh_at: datetime | None = None
        self._next_mail_check_at: datetime | None = None
        self._next_fax_check_at: datetime | None = None

    @staticmethod
    def _current_kst(now: datetime | None) -> datetime:
        current = now or datetime.now(KST)
        if current.tzinfo is None:
            current = current.replace(tzinfo=KST)
        return current.astimezone(KST)

    def _schedule_daily_digest(self, now: datetime | None) -> int:
        service = self.daily_digest
        if service is None or not service.config.enabled or service.config.owner != "worker":
            return 0
        current = self._current_kst(now)
        service.initialize(current)
        created = 0
        if self._next_digest_check_at is None or current >= self._next_digest_check_at:
            self._next_digest_check_at = current + timedelta(seconds=service.config.poll_seconds)
            if service.is_due(current):
                content = service.build(current.date())
                notifications = [
                    TextNotification(
                        key=f"daily:{current.date().isoformat()}",
                        category="daily",
                        title="",
                        message="Good Morning.",
                        priority=0,
                    )
                ]
                for event in digest_events(content):
                    event_text = event.strip()
                    punctuation = "" if event_text.endswith((".", "!", "?", "。", "！", "？")) else "."
                    event_key = hashlib.sha256(event.encode("utf-8")).hexdigest()[:16]
                    notifications.append(
                        TextNotification(
                            key=f"daily:event:{current.date().isoformat()}:{event_key}",
                            category="daily",
                            title="",
                            message=f"Today. {event_text}{punctuation}",
                            priority=0,
                        )
                    )
                created = sum(
                    1
                    for notification in notifications
                    if self.notifications.enqueue(notification)
                )
                service.record_scheduled(current.date(), content)
        # Refresh after scheduling so a slow or unavailable web source can never
        # delay the time-sensitive morning alert; cached/local content is enough.
        if self._next_content_refresh_at is None or current >= self._next_content_refresh_at:
            content_status = service.refresh_content()
            if content_status.get("lastError"):
                LOGGER.warning("Daily digest content refresh: %s", content_status["lastError"])
            self._next_content_refresh_at = current + timedelta(hours=1)
        return created

    @staticmethod
    def _current_utc(now: datetime | None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _poll_mail(self, now: datetime | None) -> ImportCycleResult:
        lifecycle = self.mail_lifecycle
        if lifecycle is None:
            return ImportCycleResult()
        current = self._current_utc(now)
        if self._next_mail_check_at is not None and current < self._next_mail_check_at:
            return ImportCycleResult()
        self._next_mail_check_at = current + timedelta(seconds=lifecycle.poller.config.poll_seconds)
        result = lifecycle.run_once()
        status = lifecycle.poller.status()
        if status.get("lastError"):
            LOGGER.warning("Naver mail scan failed: %s", status["lastError"])
        return result

    def _poll_fax(self, now: datetime | None) -> ImportCycleResult:
        lifecycle = self.fax_lifecycle
        if lifecycle is None:
            return ImportCycleResult()
        current = self._current_utc(now)
        if self._next_fax_check_at is not None and current < self._next_fax_check_at:
            return ImportCycleResult()
        self._next_fax_check_at = current + timedelta(seconds=lifecycle.service.config.poll_seconds)
        return lifecycle.run_once()

    def run_once(self, now: datetime | None = None) -> int:
        delivered = 0
        scheduled = 0
        mail_result = ImportCycleResult()
        fax_result = ImportCycleResult()
        errors = []
        try:
            delivered += self.notifications.deliver_pending()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        try:
            scheduled = self._schedule_daily_digest(now)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if self.daily_digest is not None:
                self.daily_digest.record_error(exc)
        try:
            mail_result = self._poll_mail(now)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        try:
            fax_result = self._poll_fax(now)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        if scheduled or mail_result.notification_count or fax_result.notification_count:
            try:
                delivered += self.notifications.deliver_pending()
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
        error = "; ".join(errors)
        self._write_status(
            status="degraded" if errors else "ready",
            delivered=delivered,
            scheduled=scheduled,
            mail_result=mail_result,
            fax_result=fax_result,
            error=error,
            now=now,
        )
        if errors:
            raise WorkerCycleError(error)
        return delivered

    def _write_status(
        self,
        *,
        status: str,
        delivered: int,
        scheduled: int,
        mail_result: ImportCycleResult,
        fax_result: ImportCycleResult,
        error: str,
        now: datetime | None,
    ) -> None:
        _atomic_json(
            self.config.status_path,
            {
                "version": 2,
                "status": status,
                "lastCycleAt": _timestamp(now),
                "lastDeliveredCount": delivered,
                "lastScheduledNotificationCount": scheduled,
                "lastMailProcessedCount": mail_result.processed,
                "lastFaxActionCount": fax_result.processed,
                "lastError": error,
                "pushover": self.notifications.status(),
                "dailyDigest": self.daily_digest.status() if self.daily_digest is not None else {"enabled": False},
                "naverMail": (
                    self.mail_lifecycle.poller.status()
                    if self.mail_lifecycle is not None
                    else {"enabled": False}
                ),
                "fax": (
                    self.fax_lifecycle.service.status()
                    if self.fax_lifecycle is not None
                    else {"enabled": False}
                ),
            },
        )

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                LOGGER.exception("Governor worker cycle failed")
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.notifications.config.poll_seconds,
                )
            except TimeoutError:
                continue


def validate_delivery_ownership(config: PushoverConfig) -> None:
    if config.enabled and config.delivery_mode != "worker":
        raise WorkerConfigurationError(
            "PUSHOVER_DELIVERY_MODE must be worker when kaos-governor-worker is running"
        )


def worker_healthy(
    config: WorkerConfig,
    *,
    now: datetime | None = None,
) -> bool:
    try:
        payload = json.loads(config.status_path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(str(payload["lastCycleAt"]).replace("Z", "+00:00"))
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = (current.astimezone(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
    return payload.get("status") == "ready" and 0 <= age <= config.health_stale_seconds


async def _run(worker: GovernorWorker) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    await worker.run_forever(stop)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run KaosGovernor background workers")
    parser.add_argument("--check", action="store_true", help="check worker heartbeat")
    arguments = parser.parse_args()
    pushover = PushoverConfig.from_env()
    config = WorkerConfig.from_env(poll_seconds=pushover.poll_seconds)
    if arguments.check:
        raise SystemExit(0 if worker_healthy(config) else 1)
    try:
        validate_delivery_ownership(pushover)
    except WorkerConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    digest_config = DailyDigestConfig.from_env()
    daily_digest = None
    if digest_config.enabled and digest_config.owner == "worker":
        calendar_url = os.environ.get(
            "CALENDAR_ADAPTER_INTERNAL_URL",
            "http://calendar-adapter:8091",
        ).strip()
        daily_digest = DailyDigestService(
            digest_config,
            CalendarAdapterClient(CalendarAdapterConfig(calendar_url)),
        )
    notifications = TextNotificationService(pushover)
    mail_config = NaverMailConfig.from_env()
    mail_lifecycle = None
    if mail_config.enabled and mail_config.owner == "worker":
        mail_lifecycle = NaverMailLifecycleWorker(
            NaverMailPoller(mail_config),
            notifications,
        )
    fax_config = FaxConfig.from_env()
    fax_lifecycle = None
    if fax_config.enabled and fax_config.owner == "worker":
        fax_lifecycle = FaxLifecycleWorker(
            FaxService(fax_config),
            notifications,
        )
    asyncio.run(
        _run(
            GovernorWorker(
                config,
                notifications,
                daily_digest,
                mail_lifecycle,
                fax_lifecycle,
            )
        )
    )


if __name__ == "__main__":
    main()
