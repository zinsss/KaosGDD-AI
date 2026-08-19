from __future__ import annotations

import subprocess
import unittest

from kaos_governor_discord.maintenance import (
    MaintenanceReport,
    MaintenanceTarget,
    collect_maintenance_report,
    maintenance_targets,
    parse_probe_output,
    render_maintenance_reports,
)


class MaintenanceTests(unittest.TestCase):
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
                    },
                )
            ]
        )

        self.assertIn("OS 12, Docker packages 2", text)
        self.assertIn("Docker version 27.5.1", text)
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


if __name__ == "__main__":
    unittest.main()
