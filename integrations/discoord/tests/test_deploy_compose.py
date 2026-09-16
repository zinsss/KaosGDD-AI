from pathlib import Path
import unittest


def _repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "deploy/h3-backend/compose.yaml").is_file():
            return parent
    return None


class DiscordDeployComposeTests(unittest.TestCase):
    def test_h3_runtime_no_longer_defines_discord_container_or_secret(self) -> None:
        repo_root = _repo_root()
        if repo_root is None:
            self.skipTest("deploy compose file is not copied into the isolated test image")
        compose_source = (repo_root / "deploy/h3-backend/compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("governor-discord:", compose_source)
        self.assertNotIn("discord_bot_token", compose_source)
        self.assertNotIn("integrations/discoord/Dockerfile", compose_source)
        self.assertIn("SYSTEM_MAINTENANCE_REPORT_PATH", compose_source)


if __name__ == "__main__":
    unittest.main()
