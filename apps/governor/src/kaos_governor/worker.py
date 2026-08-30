from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
from typing import Mapping

from .notifications import PushoverConfig, TextNotificationService


LOGGER = logging.getLogger(__name__)


class WorkerConfigurationError(ValueError):
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
    ) -> None:
        self.config = config
        self.notifications = notifications

    def run_once(self, now: datetime | None = None) -> int:
        try:
            delivered = self.notifications.deliver_pending()
            self._write_status(
                status="ready",
                delivered=delivered,
                error="",
                now=now,
            )
            return delivered
        except Exception as exc:
            self._write_status(
                status="degraded",
                delivered=0,
                error=f"{type(exc).__name__}: {exc}",
                now=now,
            )
            raise

    def _write_status(
        self,
        *,
        status: str,
        delivered: int,
        error: str,
        now: datetime | None,
    ) -> None:
        _atomic_json(
            self.config.status_path,
            {
                "version": 1,
                "status": status,
                "lastCycleAt": _timestamp(now),
                "lastDeliveredCount": delivered,
                "lastError": error,
                "pushover": self.notifications.status(),
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
    asyncio.run(_run(GovernorWorker(config, TextNotificationService(pushover))))


if __name__ == "__main__":
    main()
