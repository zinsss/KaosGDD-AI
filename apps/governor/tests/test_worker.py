from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest import mock

from kaos_governor.notifications import PushoverConfig
from kaos_governor.worker import (
    GovernorWorker,
    WorkerConfig,
    WorkerConfigurationError,
    validate_delivery_ownership,
    worker_healthy,
)


class GovernorWorkerTests(unittest.TestCase):
    def worker(self, root: Path, *, delivered: int = 2):
        notifications = SimpleNamespace(
            config=SimpleNamespace(poll_seconds=5),
            deliver_pending=mock.Mock(return_value=delivered),
            status=mock.Mock(return_value={"pendingCount": 0, "deliveryMode": "worker"}),
        )
        config = WorkerConfig(status_path=root / "worker.json", health_stale_seconds=60)
        return GovernorWorker(config, notifications), notifications

    def test_cycle_delivers_pending_and_writes_fresh_health(self) -> None:
        now = datetime(2026, 8, 30, 6, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            worker, notifications = self.worker(Path(temporary))

            delivered = worker.run_once(now)
            status = json.loads(worker.config.status_path.read_text(encoding="utf-8"))

            self.assertTrue(worker_healthy(worker.config, now=now + timedelta(seconds=59)))
            self.assertFalse(worker_healthy(worker.config, now=now + timedelta(seconds=61)))

        self.assertEqual(delivered, 2)
        notifications.deliver_pending.assert_called_once_with()
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["lastDeliveredCount"], 2)
        self.assertEqual(status["pushover"]["deliveryMode"], "worker")

    def test_failed_cycle_records_degraded_health(self) -> None:
        now = datetime(2026, 8, 30, 6, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            worker, notifications = self.worker(Path(temporary))
            notifications.deliver_pending.side_effect = RuntimeError("offline")

            with self.assertRaisesRegex(RuntimeError, "offline"):
                worker.run_once(now)

            status = json.loads(worker.config.status_path.read_text(encoding="utf-8"))
            healthy = worker_healthy(worker.config, now=now)

        self.assertEqual(status["status"], "degraded")
        self.assertIn("offline", status["lastError"])
        self.assertFalse(healthy)

    def test_missing_heartbeat_is_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = WorkerConfig(status_path=Path(temporary) / "missing.json")

            self.assertFalse(worker_healthy(config))

    def test_enabled_worker_rejects_inline_delivery_ownership(self) -> None:
        config = PushoverConfig(enabled=True, delivery_mode="inline")

        with self.assertRaisesRegex(WorkerConfigurationError, "must be worker"):
            validate_delivery_ownership(config)


if __name__ == "__main__":
    unittest.main()
