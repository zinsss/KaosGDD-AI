from pathlib import Path
import tempfile
import unittest

from kaos_brain.config import ConfigurationError, Settings


BASE_ENV: dict[str, str] = {}


class SettingsTests(unittest.TestCase):
    def test_parses_minimal_configuration(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        self.assertEqual(settings.chat_model, "gemma3:4b")
        self.assertEqual(settings.deep_model, "qwen3:8b")
        self.assertEqual(settings.imaging_provider, "ollama")
        self.assertEqual(settings.imaging_model, "gemma3:4b")
        self.assertFalse(settings.kaosai_enabled)
        self.assertEqual(settings.kaosai_provider, "disabled")
        self.assertEqual(settings.health_host, "127.0.0.1")
        self.assertEqual(settings.health_port, 8099)
        self.assertFalse(settings.imaging_enabled)
        self.assertEqual(settings.calendar_preview_api_token, "")
        self.assertEqual(settings.document_tag_api_token, "")
        self.assertEqual(settings.ai_task_api_token, "")
        self.assertFalse(settings.kaosai_reauth_enabled)

    def test_retired_discord_settings_are_not_required_or_loaded(self) -> None:
        settings = Settings.from_env(
            {
                "DISCORD_BOT_TOKEN_FILE": "/missing/retired-token",
                "DISCORD_GUILD_ID": "not-an-id",
                "DISCORD_ALLOWED_USER_IDS": "not-an-id",
                "DISCORD_BRAIN_CHANNEL_ID": "not-an-id",
            }
        )

        self.assertFalse(hasattr(settings, "token"))
        self.assertFalse(hasattr(settings, "guild_id"))

    def test_kaosai_configuration_is_disabled_by_default(self) -> None:
        settings = Settings.from_env({**BASE_ENV, "KAOSAI_API_TOKEN_FILE": "/missing/openclaw_gateway_token"})

        self.assertFalse(settings.kaosai_enabled)
        self.assertEqual(settings.kaosai_provider, "disabled")
        self.assertEqual(settings.kaosai_base_url, "")
        self.assertEqual(settings.kaosai_model, "default")
        self.assertEqual(settings.kaosai_api_token, "")

    def test_kaosai_requires_openclaw_provider_and_base_url_when_enabled(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_PROVIDER"):
            Settings.from_env({**BASE_ENV, "KAOSAI_ENABLED": "true", "KAOSAI_PROVIDER": "disabled"})
        with self.assertRaisesRegex(ConfigurationError, "KAOSAI_BASE_URL"):
            Settings.from_env({**BASE_ENV, "KAOSAI_ENABLED": "true", "KAOSAI_PROVIDER": "openclaw"})
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
                "KAOSAI_TIMEOUT_SECONDS": "45",
            }
        )

        self.assertTrue(settings.kaosai_enabled)
        self.assertEqual(settings.kaosai_provider, "openclaw")
        self.assertEqual(settings.kaosai_base_url, "http://127.0.0.1:18789")
        self.assertEqual(settings.kaosai_model, "gpt-5-thinking")
        self.assertEqual(settings.kaosai_api_token, "gateway-token")
        self.assertEqual(settings.kaosai_timeout_seconds, 45)

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

    def test_headless_api_bind_configuration(self) -> None:
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "KAOSBRAIN_HEALTH_HOST": "100.113.169.46",
                "KAOSBRAIN_HEALTH_PORT": "8099",
            }
        )
        self.assertEqual(settings.health_host, "100.113.169.46")
        self.assertEqual(settings.health_port, 8099)

    def test_calendar_preview_token_can_be_loaded_from_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "calendar-preview-token"
            token_file.write_text("calendar-preview-secret\n", encoding="utf-8")

            settings = Settings.from_env({**BASE_ENV, "KAOSBRAIN_CALENDAR_PREVIEW_API_TOKEN_FILE": str(token_file)})

        self.assertEqual(settings.calendar_preview_api_token, "calendar-preview-secret")

    def test_document_tag_token_can_be_loaded_from_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "document-tag-token"
            token_file.write_text("document-tag-secret\n", encoding="utf-8")

            settings = Settings.from_env({**BASE_ENV, "KAOSBRAIN_DOCUMENT_TAG_API_TOKEN_FILE": str(token_file)})

        self.assertEqual(settings.document_tag_api_token, "document-tag-secret")

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
