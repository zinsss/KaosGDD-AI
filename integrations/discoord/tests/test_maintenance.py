from __future__ import annotations

from datetime import date, datetime, timezone
import subprocess
import tempfile
import unittest
from pathlib import Path

from kaosdiscoord.maintenance import (
    MaintenanceReport,
    MaintenanceTarget,
    collect_maintenance_reports,
    collect_maintenance_report,
    due_openclaw_renewal_reminders,
    load_stored_maintenance_reports,
    maintenance_issues,
    maintenance_probe_script,
    maintenance_targets,
    openclaw_renewal_from_report,
    parse_openclaw_models_status,
    parse_probe_output,
    render_openclaw_renewal_reminder,
    render_maintenance_reports,
    render_system_maintenance_reminder,
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

    def test_probe_checks_openclaw_status_with_scoped_env_and_sanitizes_output(self) -> None:
        script = maintenance_probe_script("/srv/projects/KaosGDD-AI")

        self.assertIn('export OPENCLAW_STATE_DIR="$(dirname "$openclaw_config")"', script)
        self.assertIn('export OPENCLAW_CONFIG_PATH="$openclaw_config"', script)
        self.assertIn("nvm use 24", script)
        self.assertIn("openclaw models status --json", script)
        self.assertIn("openclaw_auth_status=", script)
        self.assertIn("openclaw_auth_expires_at=", script)
        self.assertNotIn("accessToken=", script)
        self.assertNotIn("refreshToken=", script)

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
                        "openclaw_auth_probe": "ok",
                        "openclaw_auth_status": "ok",
                        "openclaw_auth_expires_at": "2026-08-29T13:40:10Z",
                        "openclaw_last_touched": "2026-08-19T13:40:10.649Z",
                    },
                )
            ]
        )

        self.assertIn("OS 12, Docker packages 2", text)
        self.assertIn("Docker version 27.5.1", text)
        self.assertIn("OpenClaw: model openai/gpt-5.6-sol", text)
        self.assertIn("ChatGPT auth ok, expires 2026-08-29T13:40:10Z, remind 2026-08-28", text)
        self.assertIn("OpenClaw config updated: 2026-08-19T13:40:10.649Z", text)
        self.assertIn("Docker image updates are not checked automatically", text)

    def test_openclaw_status_parser_returns_only_effective_status_and_expiry(self) -> None:
        expires_at = int(datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc).timestamp() * 1000)

        facts = parse_openclaw_models_status(
            {
                "configPath": "/secret/path",
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
                            {"provider": "openai", "status": "expiring", "expiresAt": expires_at}
                        ],
                        "profiles": [
                            {
                                "provider": "openai",
                                "profileId": "must-not-leak",
                                "type": "oauth",
                                "status": "expiring",
                                "expiresAt": expires_at,
                            }
                        ],
                    },
                },
            }
        )

        self.assertEqual(facts, {"status": "expiring", "expires_at": "2026-08-29T03:00:00Z"})

    def test_openclaw_status_parser_handles_missing_runtime_auth(self) -> None:
        facts = parse_openclaw_models_status(
            {
                "auth": {
                    "runtimeAuthRoutes": [
                        {"provider": "openai", "authProvider": "openai", "status": "missing"}
                    ],
                    "missingProvidersInUse": ["openai"],
                    "oauth": {"providers": [], "profiles": []},
                }
            }
        )

        self.assertEqual(facts, {"status": "missing", "expires_at": ""})

    def test_openclaw_renewal_reminder_uses_reported_expiry(self) -> None:
        reports = [
            MaintenanceReport(
                MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/repo"),
                True,
                {
                    "openclaw_configured": "yes",
                    "openclaw_primary_model": "openai/gpt-5.6-sol",
                    "openclaw_auth_status": "ok",
                    "openclaw_auth_expires_at": "2026-08-29T03:00:00Z",
                },
            )
        ]

        self.assertEqual(due_openclaw_renewal_reminders(reports, today=date(2026, 8, 27)), [])
        reminders = due_openclaw_renewal_reminders(reports, today=date(2026, 8, 28))

        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].reminder_on, date(2026, 8, 28))
        self.assertEqual(reminders[0].expires_on, date(2026, 8, 29))
        self.assertEqual(reminders[0].expires_at, "2026-08-29T03:00:00Z")
        self.assertFalse(reminders[0].estimated)
        text = render_openclaw_renewal_reminder(reminders[0])
        self.assertIn("KaosBrain-OpenAI ChatGPT renewal", text)
        self.assertIn("auth status: ok", text)
        self.assertIn("expires at: `2026-08-29T03:00:00Z`", text)

    def test_missing_and_expired_openclaw_auth_are_immediately_actionable(self) -> None:
        base = MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/repo")
        missing = openclaw_renewal_from_report(
            MaintenanceReport(
                base,
                True,
                {"openclaw_configured": "yes", "openclaw_auth_status": "missing"},
                collected_at="2026-08-29T01:00:00Z",
            )
        )
        expired = openclaw_renewal_from_report(
            MaintenanceReport(
                base,
                True,
                {
                    "openclaw_configured": "yes",
                    "openclaw_auth_status": "expired",
                    "openclaw_auth_expires_at": "2026-08-28T01:00:00Z",
                },
                collected_at="2026-08-29T01:00:00Z",
            )
        )

        self.assertIsNotNone(missing)
        self.assertEqual(missing.reminder_on, date(2026, 8, 29))
        self.assertIsNone(missing.expires_on)
        self.assertIsNotNone(expired)
        self.assertEqual(expired.reminder_on, date(2026, 8, 29))
        self.assertEqual(expired.expires_on, date(2026, 8, 28))

    def test_expiring_openclaw_auth_without_expiry_is_immediately_actionable(self) -> None:
        reminder = openclaw_renewal_from_report(
            MaintenanceReport(
                MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/repo"),
                True,
                {"openclaw_configured": "yes", "openclaw_auth_status": "expiring"},
                collected_at="2026-08-29T01:00:00Z",
            )
        )

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder.reminder_on, date(2026, 8, 29))
        self.assertIsNone(reminder.expires_on)

    def test_unknown_openclaw_probe_does_not_guess_from_config_timestamp(self) -> None:
        reminder = openclaw_renewal_from_report(
            MaintenanceReport(
                MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/repo"),
                True,
                {
                    "openclaw_configured": "yes",
                    "openclaw_auth_probe": "error",
                    "openclaw_auth_status": "unknown",
                    "openclaw_auth_expires_at": "unknown",
                    "openclaw_last_touched": "2026-08-19T13:40:10.649Z",
                },
            )
        )

        self.assertIsNone(reminder)

    def test_legacy_report_keeps_estimated_renewal_fallback(self) -> None:
        reminder = openclaw_renewal_from_report(
            MaintenanceReport(
                MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/repo"),
                True,
                {
                    "openclaw_configured": "yes",
                    "openclaw_last_touched": "2026-08-19T13:40:10.649Z",
                },
            )
        )

        self.assertIsNotNone(reminder)
        self.assertTrue(reminder.estimated)
        self.assertEqual(reminder.expires_on, date(2026, 8, 29))

    def test_fresh_actionable_report_requires_maintenance_but_stale_report_does_not(self) -> None:
        report = MaintenanceReport(
            MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/repo"),
            True,
            {
                "os_updates": "16",
                "docker_package_updates": "1",
                "docker_unhealthy": "0",
                "reboot_required": "no",
            },
            collected_at="2026-08-29T01:00:00Z",
        )

        fresh = maintenance_issues(
            [report],
            now=datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc),
        )
        stale = maintenance_issues(
            [report],
            now=datetime(2026, 9, 2, 2, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(fresh, ("kaosbrain: 16 OS updates", "kaosbrain: 1 Docker package updates"))
        self.assertEqual(stale, ())
        self.assertIn("System maintenance required", render_system_maintenance_reminder(fresh))

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
