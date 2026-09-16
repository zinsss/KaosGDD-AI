from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from kaos_governor.maintenance_collector import (
    MaintenanceReport,
    MaintenanceTarget,
    maintenance_targets,
    parse_openclaw_models_status,
    write_report,
)


class MaintenanceCollectorTests(unittest.TestCase):
    def test_targets_keep_ssh_credentials_on_the_host_boundary(self) -> None:
        targets = maintenance_targets(
            "h3=local:/srv/projects/KaosGDD-AI,"
            "h4=ssh:zin@kaosbrain:/srv/projects/KaosGDD-AI"
        )

        self.assertEqual(targets[0], MaintenanceTarget("h3", "local", "", "/srv/projects/KaosGDD-AI"))
        self.assertEqual(
            targets[1],
            MaintenanceTarget(
                "h4",
                "ssh",
                "zin@kaosbrain",
                "/srv/projects/KaosGDD-AI",
            ),
        )

    def test_openclaw_parser_returns_only_status_and_expiry(self) -> None:
        expires_at = int(
            datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc).timestamp() * 1000
        )
        facts = parse_openclaw_models_status(
            {
                "configPath": "/secret/path",
                "token": "must-not-leak",
                "auth": {
                    "runtimeAuthRoutes": [
                        {
                            "provider": "openai",
                            "authProvider": "openai",
                            "status": "expiring",
                            "effective": {"detail": "private profile label"},
                        }
                    ],
                    "oauth": {
                        "providers": [
                            {
                                "provider": "openai",
                                "status": "expiring",
                                "expiresAt": expires_at,
                                "accessToken": "must-not-leak",
                            }
                        ],
                        "profiles": [],
                    },
                },
            }
        )

        self.assertEqual(
            facts,
            {"status": "expiring", "expires_at": "2026-09-25T03:00:00Z"},
        )

    def test_report_write_is_atomic_and_private_to_the_service_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "maintenance-report.json"
            write_report(
                path,
                [
                    MaintenanceReport(
                        MaintenanceTarget("h3", "local", "", "/repo"),
                        True,
                        {"os_updates": "0"},
                        collected_at="2026-09-17T00:00:00Z",
                    )
                ],
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            mode = path.stat().st_mode & 0o777

        self.assertEqual(payload["reports"][0]["target"]["name"], "h3")
        self.assertEqual(mode, 0o660)


if __name__ == "__main__":
    unittest.main()
