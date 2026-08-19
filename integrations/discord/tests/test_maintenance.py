from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from kaos_governor_discord.maintenance import (
    MaintenanceReport,
    MaintenanceTarget,
    collect_maintenance_reports,
    collect_maintenance_report,
    load_stored_maintenance_reports,
    maintenance_targets,
    parse_probe_output,
    render_maintenance_reports,
)


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_targets_supports_local_and_ssh_hosts(self) -> None:
        targets = maintenance_targets(
            {
                "SYSTEM_MAINTENANCE_TARGETS": (
                    "kaosgdd=local:/srv/projects/KaosGDD-AI,"
                    "kaosbrain=ssh:zin@kaosbrain:/srv/projects/KaosGDD-AI,"
                    "kaosclinic=ssh:zin@kaosclinic:"
                )
            }
        )

        self.assertEqual(
            targets,
            (
                MaintenanceTarget("kaosgdd", "local", "", "/srv/projects/KaosGDD-AI"),
                MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/srv/projects/KaosGDD-AI"),
                MaintenanceTarget("kaosclinic", "ssh", "zin@kaosclinic", ""),
            ),
        )

    def test_parse_probe_output_keeps_key_values(self) -> None:
        facts = parse_probe_output("hostname=kaosgdd\nos_updates=12\ndocker_package_updates=2\n")

        self.assertEqual(facts["hostname"], "kaosgdd")
        self.assertEqual(facts["os_updates"], "12")
        self.assertEqual(facts["docker_package_updates"], "2")

    def test_collect_report_uses_runner_without_mutating_host(self) -> None:
        target = MaintenanceTarget("kaosgdd", "local", "", "/repo")
        seen = {}

        def runner(received_target: MaintenanceTarget, script: str, timeout: float) -> subprocess.CompletedProcess[str]:
            seen["target"] = received_target
            seen["script"] = script
            seen["timeout"] = timeout
            return subprocess.CompletedProcess(
                [],
                0,
                "hostname=kaosgdd\nos_updates=1\ndocker_package_updates=1\n",
                "",
            )

        report = collect_maintenance_report(target, 5.0, runner)

        self.assertTrue(report.ok)
        self.assertEqual(report.facts["docker_package_updates"], "1")
        self.assertNotIn("docker pull", seen["script"])
        self.assertNotIn("apt-get update", seen["script"])

    def test_render_report_includes_docker_update_status(self) -> None:
        text = render_maintenance_reports(
            [
                MaintenanceReport(
                    MaintenanceTarget("kaosgdd", "local", "", "/repo"),
                    True,
                    {
                        "hostname": "kaosgdd",
                        "os_updates": "12",
                        "docker_package_updates": "2",
                        "reboot_required": "no",
                        "disk_root": "40% used, 100G free",
                        "memory": "1024MiB/32000MiB",
                        "docker_engine": "Docker version 27.5.1",
                        "docker_compose": "2.32.4",
                        "docker_running": "8",
                        "docker_unhealthy": "0",
                        "docker_exited": "1",
                        "repo": "## main...origin/main",
                        "repo_dirty": "0",
                        "openclaw_configured": "yes",
                        "openclaw_primary_model": "openai/gpt-5.6-sol",
                        "openclaw_gateway": "active",
                        "openclaw_reauth_agent": "active",
                        "openclaw_chatgpt_expires": "unknown",
                        "openclaw_last_touched": "2026-08-19T13:40:10.649Z",
                    },
                )
            ]
        )

        self.assertIn("OS 12, Docker packages 2", text)
        self.assertIn("Docker version 27.5.1", text)
        self.assertIn("OpenClaw: model openai/gpt-5.6-sol", text)
        self.assertIn("ChatGPT expires unknown", text)
        self.assertIn("OpenClaw config updated: 2026-08-19T13:40:10.649Z", text)
        self.assertIn("Docker image updates are not checked automatically", text)

    def test_render_failed_report(self) -> None:
        text = render_maintenance_reports(
            [
                MaintenanceReport(
                    MaintenanceTarget("kaosclinic", "ssh", "zin@kaosclinic", ""),
                    False,
                    {},
                    "ssh failed",
                )
            ]
        )

        self.assertIn("kaosclinic", text)
        self.assertIn("check failed", text)

    def test_load_stored_report_for_discord_container(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "maintenance.json"
            path.write_text(
                """
                {
                  "collectedAt": "2026-08-20T00:00:00Z",
                  "reports": [
                    {
                      "target": {"name": "kaosgdd", "mode": "local", "address": "", "repoPath": "/repo"},
                      "ok": true,
                      "facts": {"hostname": "kaosgdd", "os_updates": 3, "docker_package_updates": 1},
                      "error": ""
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            reports = load_stored_maintenance_reports({"SYSTEM_MAINTENANCE_REPORT_PATH": str(path)})

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].target.name, "kaosgdd")
        self.assertEqual(reports[0].facts["docker_package_updates"], "1")
        self.assertEqual(reports[0].collected_at, "2026-08-20T00:00:00Z")

    async def test_collect_defaults_to_stored_report_not_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing.json"

            def runner(*_args):
                raise AssertionError("runner should not be called")

            reports = await collect_maintenance_reports(
                {"SYSTEM_MAINTENANCE_REPORT_PATH": str(path)},
                runner=runner,
            )

        self.assertFalse(reports[0].ok)
        self.assertIn("no report yet", reports[0].error)

    async def test_collect_can_run_commands_when_explicitly_allowed(self) -> None:
        def runner(
            _target: MaintenanceTarget,
            _script: str,
            _timeout: float,
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], 0, "hostname=kaosgdd\n", "")

        reports = await collect_maintenance_reports(
            {
                "SYSTEM_MAINTENANCE_ALLOW_COMMANDS": "true",
                "SYSTEM_MAINTENANCE_TARGETS": "kaosgdd=local:/repo",
            },
            runner=runner,
        )

        self.assertTrue(reports[0].ok)
        self.assertEqual(reports[0].facts["hostname"], "kaosgdd")


if __name__ == "__main__":
    unittest.main()
