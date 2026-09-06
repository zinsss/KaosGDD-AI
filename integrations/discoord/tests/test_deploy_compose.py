from pathlib import Path
import unittest


def _repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "deploy/h3-backend/compose.yaml").is_file():
            return parent
    return None


class DiscordDeployComposeTests(unittest.TestCase):
    def test_h3_discord_container_forces_quiet_mode_for_channel_surfaces(self) -> None:
        repo_root = _repo_root()
        if repo_root is None:
            self.skipTest("deploy compose file is not copied into the isolated test image")
        compose_source = (repo_root / "deploy/h3-backend/compose.yaml").read_text(encoding="utf-8")
        quiet_overrides = {
            'MAIL_NAVER_ENABLED: "false"',
            'MAIL_NAVER_OWNER: "worker"',
            'MAIL_ORGANIZER_ENABLED: "false"',
            'FAX_DISCORD_ENABLED: "false"',
            'FAX_DISCORD_MESSAGE_INTAKE: "false"',
            'DAILY_DIGEST_ENABLED: "false"',
            'DISCORD_CALENDAR_ENABLED: "false"',
            'DISCORD_TASKS_ENABLED: "false"',
            'DISCORD_TASK_DUE_NOTIFICATIONS_ENABLED: "false"',
            'DISCORD_SUPPLIES_ENABLED: "false"',
            'DISCORD_MEMOS_ENABLED: "false"',
            'DISCORD_INBOX_ENABLED: "false"',
            'DISCORD_SERVICE_STATUS_ENABLED: "false"',
            'DISCORD_STARTUP_NOTIFICATION: "false"',
        }
        for expected in quiet_overrides:
            with self.subTest(expected=expected):
                self.assertIn(expected, compose_source)


if __name__ == "__main__":
    unittest.main()
