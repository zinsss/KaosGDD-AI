from pathlib import Path
import tempfile
import unittest

from kaos_brain.config import ConfigurationError, Settings


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200,201",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
}


class SettingsTests(unittest.TestCase):
    def test_parses_minimal_configuration(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        self.assertEqual(settings.guild_id, 100)
        self.assertEqual(settings.allowed_user_ids, frozenset({200, 201}))
        self.assertEqual(settings.brain_channel_id, 300)
        self.assertEqual(settings.chat_model, "gemma3:4b")
        self.assertEqual(settings.deep_model, "qwen3:8b")
        self.assertTrue(settings.respond_without_mention)
        self.assertTrue(settings.auto_route_enabled)

    def test_token_can_be_loaded_from_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "discord-token"
            token_file.write_text("discord-file-secret\n", encoding="utf-8")
            env = {**BASE_ENV, "DISCORD_BOT_TOKEN": "", "DISCORD_BOT_TOKEN_FILE": str(token_file)}
            settings = Settings.from_env(env)
        self.assertEqual(settings.token, "discord-file-secret")

    def test_rejects_ambiguous_secret_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "discord-token"
            token_file.write_text("discord-file-secret\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                Settings.from_env({**BASE_ENV, "DISCORD_BOT_TOKEN_FILE": str(token_file)})

    def test_requires_explicit_allowed_users(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_ALLOWED_USER_IDS": ""})

    def test_caps_discord_reply_length(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "KAOSBRAIN_MAX_REPLY_CHARS": "2000"})

    def test_auto_route_can_be_disabled(self) -> None:
        settings = Settings.from_env({**BASE_ENV, "KAOSBRAIN_AUTO_ROUTE_ENABLED": "false"})
        self.assertFalse(settings.auto_route_enabled)


if __name__ == "__main__":
    unittest.main()
