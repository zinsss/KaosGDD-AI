from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from kaos_runbook_planner import (
    MaintenanceReportError,
    StoredMaintenanceReportAdapter,
)
from kaos_runbook_planner.maintenance_adapter import (
    MAINTENANCE_REPORT_PATH,
    MAX_REPORT_BYTES,
)


NOW = datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)


def report_bytes(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "collectedAt": "2026-09-02T02:30:00Z",
        "reports": [
            {
                "target": {
                    "name": "kaosgdd",
                    "mode": "local",
                    "address": "",
                    "repoPath": "/srv/projects/KaosGDD-AI",
                },
                "ok": True,
                "facts": {
                    "hostname": "kaosgdd",
                    "os_updates": "12",
                    "docker_package_updates": "2",
                    "reboot_required": "no",
                    "docker_running": "8",
                    "docker_unhealthy": "0",
                    "docker_exited": "1",
                    "docker_image_updates": "not checked; requires explicit pull",
                },
                "error": "",
            }
        ],
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class StoredMaintenanceReportAdapterTests(unittest.TestCase):
    def test_parses_fresh_allowlisted_h3_report(self) -> None:
        result = StoredMaintenanceReportAdapter.parse(report_bytes(), now=NOW)

        self.assertTrue(result["readOnly"])
        self.assertEqual(result["host"], "kaosgdd")
        self.assertEqual(result["ageSeconds"], 1_800)
        self.assertEqual(result["updates"]["routinePackageCount"], 12)
        self.assertEqual(result["updates"]["dockerEnginePackageCount"], 2)
        self.assertFalse(result["updates"]["containerImagesChecked"])
        self.assertEqual(result["updates"]["containerImageStatus"], "not-checked")
        self.assertEqual(result["containers"]["unhealthy"], 0)

    def test_read_uses_only_the_fixed_report_path(self) -> None:
        adapter = StoredMaintenanceReportAdapter()
        with patch.object(
            type(MAINTENANCE_REPORT_PATH),
            "read_bytes",
            autospec=True,
            return_value=report_bytes(),
        ) as read_bytes:
            result = adapter.read(now=NOW)

        self.assertEqual(result["source"], "stored-maintenance-report")
        read_bytes.assert_called_once_with(MAINTENANCE_REPORT_PATH)

    def test_missing_or_invalid_report_fails_closed(self) -> None:
        with patch.object(
            type(MAINTENANCE_REPORT_PATH),
            "read_bytes",
            autospec=True,
            side_effect=FileNotFoundError,
        ):
            with self.assertRaisesRegex(MaintenanceReportError, "unavailable"):
                StoredMaintenanceReportAdapter().read(now=NOW)

        for content in (b"", b"not-json", b"[]"):
            with self.subTest(content=content), self.assertRaises(
                MaintenanceReportError
            ):
                StoredMaintenanceReportAdapter.parse(content, now=NOW)

    def test_oversized_or_stale_report_fails_closed(self) -> None:
        with self.assertRaisesRegex(MaintenanceReportError, "size limit"):
            StoredMaintenanceReportAdapter.parse(
                b"x" * (MAX_REPORT_BYTES + 1), now=NOW
            )
        with self.assertRaisesRegex(MaintenanceReportError, "stale"):
            StoredMaintenanceReportAdapter.parse(
                report_bytes(collectedAt="2026-08-30T00:00:00Z"), now=NOW
            )

    def test_wrong_missing_or_duplicate_target_fails_closed(self) -> None:
        base = json.loads(report_bytes())
        for reports in (
            [],
            [{"target": {"name": "kaosbrain"}, "ok": True, "facts": {}}],
            base["reports"] * 2,
        ):
            with self.subTest(reports=reports), self.assertRaisesRegex(
                MaintenanceReportError, "exactly one"
            ):
                StoredMaintenanceReportAdapter.parse(
                    report_bytes(reports=reports), now=NOW
                )

    def test_failed_probe_hostname_mismatch_and_invalid_counts_fail_closed(self) -> None:
        mutations = (
            ("ok", False),
            ("hostname", "kaosbrain"),
            ("os_updates", "unknown"),
            ("docker_unhealthy", -1),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                payload = json.loads(report_bytes())
                report = payload["reports"][0]
                if field == "ok":
                    report["ok"] = value
                else:
                    report["facts"][field] = value
                with self.assertRaises(MaintenanceReportError):
                    StoredMaintenanceReportAdapter.parse(
                        json.dumps(payload).encode("utf-8"), now=NOW
                    )

    def test_future_timestamp_or_invalid_reboot_state_fails_closed(self) -> None:
        with self.assertRaisesRegex(MaintenanceReportError, "future"):
            StoredMaintenanceReportAdapter.parse(
                report_bytes(collectedAt="2026-09-02T03:06:00Z"), now=NOW
            )
        payload = json.loads(report_bytes())
        payload["reports"][0]["facts"]["reboot_required"] = "maybe"
        with self.assertRaisesRegex(MaintenanceReportError, "reboot-required"):
            StoredMaintenanceReportAdapter.parse(
                json.dumps(payload).encode("utf-8"), now=NOW
            )


if __name__ == "__main__":
    unittest.main()
