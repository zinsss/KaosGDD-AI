from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest import mock

from kaos_governor.notifications import PushoverConfig
from kaos_governor.daily_digest import KST
from kaos_governor.import_workers import ImportCycleResult
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
            enqueue=mock.Mock(return_value=True),
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
        self.assertEqual(status["lastScheduledNotificationCount"], 0)
        self.assertEqual(status["lastMailProcessedCount"], 0)
        self.assertEqual(status["lastFaxActionCount"], 0)
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

    def test_worker_schedules_normal_priority_digest_then_delivers_it(self) -> None:
        now = datetime(2026, 8, 29, 7, 0, tzinfo=KST)
        daily_digest = SimpleNamespace(
            config=SimpleNamespace(enabled=True, owner="worker", poll_seconds=30),
            initialize=mock.Mock(),
            refresh_content=mock.Mock(return_value={"lastError": ""}),
            is_due=mock.Mock(return_value=True),
            build=mock.Mock(
                return_value="# 2026.08.29(Sat)\n### Events\n- Christmas\n\n### Tasks\n-"
            ),
            record_scheduled=mock.Mock(),
            record_error=mock.Mock(),
            status=mock.Mock(return_value={"enabled": True, "owner": "worker"}),
        )
        notifications = SimpleNamespace(
            config=SimpleNamespace(poll_seconds=5),
            deliver_pending=mock.Mock(side_effect=[0, 2]),
            enqueue=mock.Mock(return_value=True),
            status=mock.Mock(return_value={"pendingCount": 0, "deliveryMode": "worker"}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            worker = GovernorWorker(
                WorkerConfig(status_path=Path(temporary) / "worker.json"),
                notifications,
                daily_digest,
            )

            delivered = worker.run_once(now)
            status = json.loads(worker.config.status_path.read_text(encoding="utf-8"))

        queued = [call.args[0] for call in notifications.enqueue.call_args_list]
        self.assertEqual(delivered, 2)
        self.assertEqual([item.message for item in queued], ["Good Morning.", "Today. Christmas."])
        self.assertEqual([item.priority for item in queued], [0, 0])
        daily_digest.record_scheduled.assert_called_once_with(now.date(), daily_digest.build.return_value)
        self.assertEqual(status["lastScheduledNotificationCount"], 2)
        self.assertEqual(status["dailyDigest"]["owner"], "worker")

    def test_worker_polls_mail_and_fax_at_their_own_intervals(self) -> None:
        now = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)
        notifications = SimpleNamespace(
            config=SimpleNamespace(poll_seconds=5),
            deliver_pending=mock.Mock(side_effect=[0, 2, 0]),
            enqueue=mock.Mock(return_value=True),
            status=mock.Mock(return_value={"pendingCount": 0, "deliveryMode": "worker"}),
        )
        mail = SimpleNamespace(
            poller=SimpleNamespace(
                config=SimpleNamespace(poll_seconds=60),
                status=mock.Mock(return_value={"enabled": True, "owner": "worker", "lastError": ""}),
            ),
            run_once=mock.Mock(return_value=ImportCycleResult(1, 1)),
        )
        fax = SimpleNamespace(
            service=SimpleNamespace(
                config=SimpleNamespace(poll_seconds=20),
                status=mock.Mock(return_value={"enabled": True, "owner": "worker", "lastError": ""}),
            ),
            run_once=mock.Mock(return_value=ImportCycleResult(3, 1)),
        )
        with tempfile.TemporaryDirectory() as temporary:
            worker = GovernorWorker(
                WorkerConfig(status_path=Path(temporary) / "worker.json"),
                notifications,
                mail_lifecycle=mail,
                fax_lifecycle=fax,
            )

            delivered = worker.run_once(now)
            worker.run_once(now + timedelta(seconds=5))
            status = json.loads(worker.config.status_path.read_text(encoding="utf-8"))

        self.assertEqual(delivered, 2)
        mail.run_once.assert_called_once_with()
        fax.run_once.assert_called_once_with()
        self.assertEqual(status["lastMailProcessedCount"], 0)
        self.assertEqual(status["lastFaxActionCount"], 0)
        self.assertEqual(status["naverMail"]["owner"], "worker")
        self.assertEqual(status["fax"]["owner"], "worker")

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
