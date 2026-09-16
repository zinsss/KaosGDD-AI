from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from kaos_governor.maintenance import (
    DEFAULT_REPORT_PATH,
    MaintenanceReminderConfig,
    MaintenanceReminderService,
    load_stored_maintenance_reports,
)
from kaos_governor.notifications import (
    NotificationInbox,
    NotificationInboxConfig,
    PushoverConfig,
    TextNotificationService,
)


NOW = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)


def write_report(
    path: Path,
    *,
    collected_at: datetime = NOW,
    auth_status: str = "expiring",
    expires_at: str = "2026-09-18T08:00:00Z",
    os_updates: str = "3",
) -> None:
    path.write_text(
        json.dumps(
            {
                "collectedAt": collected_at.isoformat().replace("+00:00", "Z"),
                "reports": [
                    {
                        "target": {
                            "name": "kaosbrain",
                            "mode": "ssh",
                            "address": "zin@kaosbrain",
                            "repoPath": "/srv/projects/KaosGDD-AI",
                        },
                        "ok": True,
                        "facts": {
                            "os_updates": os_updates,
                            "docker_package_updates": "0",
                            "docker_unhealthy": "0",
                            "reboot_required": "no",
                            "openclaw_configured": "yes",
                            "openclaw_primary_model": "openai-codex/gpt-5.3-codex",
                            "openclaw_auth_status": auth_status,
                            "openclaw_auth_expires_at": expires_at,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class MaintenanceReminderTests(unittest.TestCase):
    def test_configuration_defaults_to_neutral_notification_state(self) -> None:
        config = MaintenanceReminderConfig.from_env({})

        self.assertTrue(config.enabled)
        self.assertEqual(config.report_path, DEFAULT_REPORT_PATH)
        self.assertNotIn("discord", str(config.report_path).lower())

    def test_fresh_report_enqueues_inbox_and_mirror_without_discord(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "maintenance-report.json"
            write_report(report_path)
            mirror = SimpleNamespace(enqueue=mock.Mock(return_value=True))
            notifications = TextNotificationService(
                PushoverConfig(enabled=False, state_path=root / "pushover.json"),
                inbox=NotificationInbox(
                    NotificationInboxConfig(state_path=root / "inbox.json")
                ),
                mirrors=(mirror,),
            )
            service = MaintenanceReminderService(
                MaintenanceReminderConfig(
                    report_path=report_path,
                    state_path=root / "maintenance-reminders.json",
                    poll_seconds=3600,
                    max_report_age_seconds=172800,
                ),
                notifications,
            )

            scheduled = service.run_due(NOW)
            skipped = service.run_due(NOW + timedelta(minutes=30))
            inbox = notifications.inbox.list_items()

        self.assertEqual(scheduled, 2)
        self.assertEqual(skipped, 0)
        self.assertEqual(inbox["pendingCount"], 2)
        self.assertEqual(inbox["criticalCount"], 2)
        self.assertEqual(mirror.enqueue.call_count, 2)
        messages = {item["message"] for item in inbox["items"]}
        self.assertIn("kaosbrain: 3 OS updates", messages)
        self.assertTrue(any("expires on 2026-09-18" in message for message in messages))

    def test_stale_report_never_replays_old_auth_or_system_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "maintenance-report.json"
            write_report(
                report_path,
                collected_at=NOW - timedelta(days=3),
                auth_status="missing",
                expires_at="unknown",
            )
            notifications = mock.Mock()
            service = MaintenanceReminderService(
                MaintenanceReminderConfig(
                    report_path=report_path,
                    state_path=root / "maintenance-reminders.json",
                    max_report_age_seconds=172800,
                ),
                notifications,
            )

            scheduled = service.run_due(NOW)

        self.assertEqual(scheduled, 0)
        notifications.enqueue.assert_not_called()
        self.assertEqual(service.status()["lastActionableCount"], 0)

    def test_migrated_discord_sent_keys_prevent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "maintenance-report.json"
            state_path = root / "maintenance-reminders.json"
            write_report(report_path, os_updates="0")
            state_path.write_text(
                json.dumps(
                    {
                        "sent": [
                            "openclaw-chatgpt:kaosbrain:2026-09-18T08:00:00Z"
                        ]
                    }
                ),
                encoding="utf-8",
            )
            notifications = mock.Mock()
            service = MaintenanceReminderService(
                MaintenanceReminderConfig(
                    report_path=report_path,
                    state_path=state_path,
                ),
                notifications,
            )

            scheduled = service.run_due(NOW)

        self.assertEqual(scheduled, 0)
        notifications.enqueue.assert_not_called()

    def test_missing_or_invalid_report_is_non_actionable_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing.json"
            reports = load_stored_maintenance_reports(path)
            service = MaintenanceReminderService(
                MaintenanceReminderConfig(
                    report_path=path,
                    state_path=Path(temporary) / "maintenance-reminders.json",
                ),
                mock.Mock(),
            )

            scheduled = service.run_due(NOW)

        self.assertFalse(reports[0].ok)
        self.assertEqual(scheduled, 0)
        self.assertIn("unavailable", service.status()["lastError"])


if __name__ == "__main__":
    unittest.main()
