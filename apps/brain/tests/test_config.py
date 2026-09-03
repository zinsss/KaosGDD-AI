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
        self.assertEqual(settings.notification_channel_id, 0)
        self.assertEqual(settings.governor_bot_user_id, 0)
        self.assertEqual(settings.chat_model, "gemma3:4b")
        self.assertEqual(settings.deep_model, "qwen3:8b")
        self.assertEqual(settings.imaging_provider, "ollama")
        self.assertEqual(settings.imaging_model, "gemma3:4b")
        self.assertTrue(settings.respond_without_mention)
        self.assertTrue(settings.auto_route_enabled)
        self.assertFalse(settings.kaosai_enabled)
        self.assertEqual(settings.kaosai_provider, "disabled")
        self.assertFalse(settings.health_enabled)
        self.assertEqual(settings.health_host, "127.0.0.1")
        self.assertEqual(settings.health_port, 8099)
        self.assertFalse(settings.imaging_enabled)
        self.assertEqual(settings.calendar_preview_api_token, "")
        self.assertFalse(settings.kaosai_reauth_enabled)
        self.assertEqual(settings.active_control_repost_seconds, 7200)
        self.assertEqual(settings.active_control_quiet_start_hour, 0)
        self.assertEqual(settings.active_control_quiet_end_hour, 7)

    def test_notification_refresh_ids_are_configured_together(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "configured together"):
            Settings.from_env({**BASE_ENV, "DISCORD_NOTIFICATION_CHANNEL_ID": "301"})

        settings = Settings.from_env(
            {
                **BASE_ENV,
                "DISCORD_NOTIFICATION_CHANNEL_ID": "301",
                "DISCORD_GOVERNOR_BOT_USER_ID": "400",
            }
        )

        self.assertEqual(settings.notification_channel_id, 301)
        self.assertEqual(settings.governor_bot_user_id, 400)

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

    def test_kaosai_configuration_is_disabled_by_default(self) -> None:
        settings = Settings.from_env({**BASE_ENV, "KAOSAI_API_TOKEN_FILE": "/missing/openclaw_gateway_token"})

        self.assertFalse(settings.kaosai_enabled)
        self.assertEqual(settings.kaosai_provider, "disabled")
        self.assertEqual(settings.kaosai_base_url, "")
        self.assertEqual(settings.kaosai_model, "default")
        self.assertEqual(settings.kaosai_api_token, "")
        self.assertFalse(settings.kaosai_chat_enabled)
        self.assertFalse(settings.kaosai_dry_run_enabled)

    def test_kaosai_requires_openclaw_provider_and_base_url_when_enabled(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_PROVIDER"):
            Settings.from_env({**BASE_ENV, "KAOSAI_ENABLED": "true", "KAOSAI_PROVIDER": "disabled"})
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_BASE_URL"):
            Settings.from_env({**BASE_ENV, "KAOSAI_ENABLED": "true", "KAOSAI_PROVIDER": "openclaw"})
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_ENABLED"):
            Settings.from_env({**BASE_ENV, "KAOSAI_DRY_RUN_ENABLED": "true"})
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_ENABLED"):
            Settings.from_env({**BASE_ENV, "KAOSAI_CHAT_ENABLED": "true"})
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_API_TOKEN"):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "KAOSAI_ENABLED": "true",
                    "KAOSAI_PROVIDER": "openclaw",
                    "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                }
            )

        settings = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSAI_ENABLED": "true",
                "KAOSAI_PROVIDER": "openclaw",
                "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                "KAOSAI_MODEL": "gpt-5-thinking",
                "KAOSAI_API_TOKEN": "gateway-token",
                "KAOSAI_CHAT_ENABLED": "true",
                "KAOSAI_TIMEOUT_SECONDS": "45",
            }
        )

        self.assertTrue(settings.kaosai_enabled)
        self.assertEqual(settings.kaosai_provider, "openclaw")
        self.assertEqual(settings.kaosai_base_url, "http://127.0.0.1:18789")
        self.assertEqual(settings.kaosai_model, "gpt-5-thinking")
        self.assertEqual(settings.kaosai_api_token, "gateway-token")
        self.assertTrue(settings.kaosai_chat_enabled)
        self.assertFalse(settings.kaosai_dry_run_enabled)
        self.assertEqual(settings.kaosai_timeout_seconds, 45)

        with self.assertRaisesRegex(ConfigurationError, "cannot both be true"):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "KAOSAI_ENABLED": "true",
                    "KAOSAI_PROVIDER": "openclaw",
                    "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                    "KAOSAI_API_TOKEN": "gateway-token",
                    "KAOSAI_CHAT_ENABLED": "true",
                    "KAOSAI_DRY_RUN_ENABLED": "true",
                }
            )

    def test_governor_tools_require_token_and_base_url(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
                    "GOVERNOR_API_TOKEN": "token",
                }
            )
        for url in (
            "https://100.64.0.1:8098",
            "http://kaosgdd.net:8098",
            "http://governor.kaosgdd.net:8098",
            "http://100.64.0.1:8098/tools/today",
            "http://user:pass@100.64.0.1:8098",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ConfigurationError, "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL"):
                Settings.from_env(
                    {
                        **BASE_ENV,
                        "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
                        "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL": url,
                        "GOVERNOR_API_TOKEN": "token",
                    }
                )

    def test_governor_tools_parse_configuration(self) -> None:
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
                "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL": "http://100.64.0.1:8098",
                "KAOSBRAIN_GOVERNOR_TOOLS_PROFILE": "family",
                "KAOSBRAIN_SUPPLIES_COLLECTION_ID": "supplies:abc",
                "GOVERNOR_API_TOKEN": "token",
            }
        )
        self.assertTrue(settings.governor_tools_enabled)
        self.assertEqual(settings.governor_tools_base_url, "http://100.64.0.1:8098")
        self.assertEqual(settings.governor_tools_profile, "family")
        self.assertEqual(settings.governor_tools_supplies_collection_id, "supplies:abc")
        self.assertEqual(settings.active_control_state_path, "/data/kaosbrain/active-control.json")
        self.assertEqual(settings.active_control_repost_seconds, 7200)
        self.assertEqual(settings.active_control_quiet_start_hour, 0)
        self.assertEqual(settings.active_control_quiet_end_hour, 7)

        disabled_repost = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
                "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL": "http://100.64.0.1:8098",
                "KAOSBRAIN_ACTIVE_CONTROL_REPOST_SECONDS": "0",
                "GOVERNOR_API_TOKEN": "token",
            }
        )
        self.assertEqual(disabled_repost.active_control_repost_seconds, 0)

        custom_window = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_ACTIVE_CONTROL_QUIET_START_HOUR": "23",
                "KAOSBRAIN_ACTIVE_CONTROL_QUIET_END_HOUR": "6",
            }
        )
        self.assertEqual(custom_window.active_control_quiet_start_hour, 23)
        self.assertEqual(custom_window.active_control_quiet_end_hour, 6)

        for name, value in (
            ("KAOSBRAIN_ACTIVE_CONTROL_QUIET_START_HOUR", "24"),
            ("KAOSBRAIN_ACTIVE_CONTROL_QUIET_END_HOUR", "-1"),
        ):
            with self.subTest(name=name), self.assertRaises(ConfigurationError):
                Settings.from_env({**BASE_ENV, name: value})

        magic_dns = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED": "true",
                "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL": "http://kaosgovernor:8098/",
                "GOVERNOR_API_TOKEN": "token",
            }
        )
        self.assertEqual(magic_dns.governor_tools_base_url, "http://kaosgovernor:8098")

    def test_imaging_endpoint_requires_token_when_enabled(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "KAOSBRAIN_IMAGING_API_TOKEN"):
            Settings.from_env({**BASE_ENV, "KAOSBRAIN_IMAGING_ENABLED": "true"})
        with self.assertRaisesRegex(ConfigurationError, "KAOSBRAIN_IMAGING_PROVIDER"):
            Settings.from_env({**BASE_ENV, "KAOSBRAIN_IMAGING_PROVIDER": "chatgpt"})
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_ENABLED"):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "KAOSBRAIN_IMAGING_ENABLED": "true",
                    "KAOSBRAIN_IMAGING_PROVIDER": "kaosai",
                    "KAOSBRAIN_IMAGING_API_TOKEN": "not-a-real-secret",
                }
            )

        settings = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_IMAGING_ENABLED": "true",
                "KAOSBRAIN_IMAGING_API_TOKEN": "not-a-real-secret",
            }
        )

        self.assertTrue(settings.imaging_enabled)
        self.assertEqual(settings.imaging_api_token, "not-a-real-secret")
        self.assertEqual(settings.imaging_provider, "ollama")
        self.assertEqual(settings.imaging_model, "gemma3:4b")

        kaosai = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_IMAGING_ENABLED": "true",
                "KAOSBRAIN_IMAGING_PROVIDER": "kaosai",
                "KAOSBRAIN_IMAGING_API_TOKEN": "not-a-real-secret",
                "KAOSAI_ENABLED": "true",
                "KAOSAI_PROVIDER": "openclaw",
                "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                "KAOSAI_API_TOKEN": "gateway-token",
            }
        )
        self.assertEqual(kaosai.imaging_provider, "kaosai")

        renamed_provider = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_IMAGING_ENABLED": "true",
                "KAOSBRAIN_IMAGING_PROVIDER": "kaosbrain-openai",
                "KAOSBRAIN_IMAGING_API_TOKEN": "not-a-real-secret",
                "KAOSAI_ENABLED": "true",
                "KAOSAI_PROVIDER": "openclaw",
                "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                "KAOSAI_API_TOKEN": "gateway-token",
            }
        )
        self.assertEqual(renamed_provider.imaging_provider, "kaosai")

    def test_imaging_model_can_be_configured_independently(self) -> None:
        settings = Settings.from_env({**BASE_ENV, "KAOSBRAIN_IMAGING_MODEL": "llava:7b"})

        self.assertEqual(settings.chat_model, "gemma3:4b")
        self.assertEqual(settings.deep_model, "qwen3:8b")
        self.assertEqual(settings.imaging_model, "llava:7b")

    def test_memos_public_url_is_optional(self) -> None:
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_MEMOS_PUBLIC_URL": "https://memos.example/",
                "KAOSBRAIN_PAPERLESS_PUBLIC_URL": "https://paperless.example/",
            }
        )
        self.assertEqual(settings.memos_public_url, "https://memos.example")
        self.assertEqual(settings.paperless_public_url, "https://paperless.example")

    def test_health_configuration_is_optional(self) -> None:
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_HEALTH_ENABLED": "true",
                "KAOSBRAIN_HEALTH_HOST": "100.113.169.46",
                "KAOSBRAIN_HEALTH_PORT": "8099",
            }
        )

        self.assertTrue(settings.health_enabled)
        self.assertEqual(settings.health_host, "100.113.169.46")
        self.assertEqual(settings.health_port, 8099)

    def test_calendar_preview_token_can_be_loaded_from_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "calendar-preview-token"
            token_file.write_text("calendar-preview-secret\n", encoding="utf-8")

            settings = Settings.from_env({**BASE_ENV, "KAOSBRAIN_CALENDAR_PREVIEW_API_TOKEN_FILE": str(token_file)})

        self.assertEqual(settings.calendar_preview_api_token, "calendar-preview-secret")

    def test_kaosai_reauth_requires_local_agent_url_and_token(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_REAUTH_BASE_URL"):
            Settings.from_env({**BASE_ENV, "KAOSAI_REAUTH_ENABLED": "true", "KAOSAI_REAUTH_BASE_URL": ""})
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_REAUTH_TOKEN"):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "KAOSAI_REAUTH_ENABLED": "true",
                    "KAOSAI_REAUTH_BASE_URL": "http://127.0.0.1:18997",
                }
            )

        settings = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSAI_REAUTH_ENABLED": "true",
                "KAOSAI_REAUTH_BASE_URL": "http://127.0.0.1:18997",
                "KAOSAI_REAUTH_TOKEN": "reauth-token",
                "KAOSAI_REAUTH_TIMEOUT_SECONDS": "12",
            }
        )

        self.assertTrue(settings.kaosai_reauth_enabled)
        self.assertEqual(settings.kaosai_reauth_base_url, "http://127.0.0.1:18997")
        self.assertEqual(settings.kaosai_reauth_api_token, "reauth-token")
        self.assertEqual(settings.kaosai_reauth_timeout_seconds, 12)


if __name__ == "__main__":
    unittest.main()
