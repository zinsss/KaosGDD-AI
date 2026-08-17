from types import SimpleNamespace
import unittest

from kaos_brain.config import Settings
from kaos_brain.health import snapshot


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
    "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL": "http://100.78.124.43:8098",
    "GOVERNOR_API_TOKEN": "token",
}


class BrainHealthTests(unittest.TestCase):
    def test_snapshot_reports_brain_runtime_status_without_secrets(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        bot = SimpleNamespace(is_ready=lambda: True)

        payload = snapshot(settings, bot).payload()

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["discordReady"])
        self.assertEqual(payload["chatModel"], "gemma3:4b")
        self.assertEqual(payload["deepModel"], "qwen3:8b")
        self.assertEqual(payload["governorTools"], {"enabled": True})
        self.assertNotIn("token", str(payload).lower())


if __name__ == "__main__":
    unittest.main()
