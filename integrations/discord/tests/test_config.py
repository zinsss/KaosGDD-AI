from pathlib import Path
import tempfile
import unittest

from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.config import ConfigurationError, Settings

BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200,201",
    "DISCORD_ALLOWED_CHANNEL_IDS": "300,301",
    "DISCORD_SYSTEM_CHANNEL_ID": "301",
}


class SettingsTests(unittest.TestCase):
    def test_parses_restricted_configuration(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        self.assertEqual(settings.guild_id, 100)
        self.assertEqual(settings.allowed_user_ids, frozenset({200, 201}))
        self.assertFalse(settings.startup_notification)

    def test_discord_token_can_be_loaded_from_a_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "discord-token"
            token_file.write_text("discord-file-secret\n", encoding="utf-8")
            env = {**BASE_ENV, "DISCORD_BOT_TOKEN": "", "DISCORD_BOT_TOKEN_FILE": str(token_file)}
            settings = Settings.from_env(env)
        self.assertEqual(settings.token, "discord-file-secret")

    def test_rejects_system_channel_outside_allowlist(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_SYSTEM_CHANNEL_ID": "999"})

    def test_requires_explicit_users(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_ALLOWED_USER_IDS": ""})

    def test_mail_channel_must_be_explicit_and_allowed(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "MAIL_NAVER_ENABLED": "true"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {**BASE_ENV, "MAIL_NAVER_ENABLED": "true", "MAIL_ARCHIVE_DISCORD_CHANNEL_ID": "999"}
            )
        settings = Settings.from_env(
            {**BASE_ENV, "MAIL_NAVER_ENABLED": "true", "MAIL_ARCHIVE_DISCORD_CHANNEL_ID": "300"}
        )
        self.assertEqual(settings.mail_archive_channel_id, 300)

    def test_organizer_also_requires_an_allowed_mail_channel(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "MAIL_ORGANIZER_ENABLED": "true"})
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "MAIL_ORGANIZER_ENABLED": "true",
                "MAIL_ARCHIVE_DISCORD_CHANNEL_ID": "300",
                "MAIL_ORGANIZER_DISCORD_CHANNEL_ID": "300",
            }
        )
        self.assertEqual(settings.mail_organizer_channel_id, 300)

    def test_archive_and_organizer_can_use_distinct_channels(self) -> None:
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "MAIL_NAVER_ENABLED": "true",
                "MAIL_ORGANIZER_ENABLED": "true",
                "MAIL_ARCHIVE_DISCORD_CHANNEL_ID": "300",
                "MAIL_ORGANIZER_DISCORD_CHANNEL_ID": "301",
            }
        )
        self.assertEqual(settings.mail_archive_channel_id, 300)
        self.assertEqual(settings.mail_organizer_channel_id, 301)

    def test_legacy_single_channel_remains_a_compatibility_fallback(self) -> None:
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "MAIL_NAVER_ENABLED": "true",
                "MAIL_ORGANIZER_ENABLED": "true",
                "MAIL_DISCORD_CHANNEL_ID": "300",
            }
        )
        self.assertEqual(settings.mail_archive_channel_id, 300)
        self.assertEqual(settings.mail_organizer_channel_id, 300)

    def test_fax_requires_two_allowed_channel_assignments(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "FAX_DISCORD_ENABLED": "true"})
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "FAX_DISCORD_ENABLED": "true",
                "FAX_ARCHIVE_DISCORD_CHANNEL_ID": "300",
                "FAX_NOTIFICATION_DISCORD_CHANNEL_ID": "301",
            }
        )
        self.assertEqual(settings.fax_archive_channel_id, 300)
        self.assertEqual(settings.fax_notification_channel_id, 301)

    def test_fax_message_intake_is_disabled_by_default(self) -> None:
        self.assertFalse(Settings.from_env(BASE_ENV).fax_message_intake)

    def test_fax_message_intake_cannot_enable_fax_implicitly(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "FAX_DISCORD_MESSAGE_INTAKE": "true"})

    def test_calendar_surface_is_disabled_by_default(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        self.assertFalse(settings.calendar_enabled)
        self.assertIsNone(settings.calendar_channel_id)
        self.assertEqual(settings.calendar_profile, "main")

    def test_calendar_surface_requires_allowed_channel_when_enabled(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_CALENDAR_ENABLED": "true"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {**BASE_ENV, "DISCORD_CALENDAR_ENABLED": "true", "DISCORD_CALENDAR_CHANNEL_ID": "999"}
            )
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "DISCORD_CALENDAR_ENABLED": "true",
                "DISCORD_CALENDAR_CHANNEL_ID": "300",
                "DISCORD_CALENDAR_PROFILE": "family",
                "DISCORD_CALENDAR_STATE_PATH": "/tmp/calendar-state.json",
                "CALENDAR_ADAPTER_INTERNAL_URL": "http://calendar-adapter:8091",
            }
        )
        self.assertTrue(settings.calendar_enabled)
        self.assertEqual(settings.calendar_channel_id, 300)
        self.assertEqual(settings.calendar_profile, "family")
        self.assertEqual(str(settings.calendar_state_path), "/tmp/calendar-state.json")
        self.assertEqual(settings.calendar_adapter_url, "http://calendar-adapter:8091")

    def test_calendar_surface_rejects_unknown_profile(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "DISCORD_CALENDAR_ENABLED": "true",
                    "DISCORD_CALENDAR_CHANNEL_ID": "300",
                    "DISCORD_CALENDAR_PROFILE": "clinic",
                }
            )

    def test_tasks_surface_is_disabled_by_default(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        self.assertFalse(settings.tasks_enabled)
        self.assertIsNone(settings.tasks_channel_id)
        self.assertEqual(settings.tasks_profile, "main")

    def test_tasks_surface_requires_allowed_channel_when_enabled(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_TASKS_ENABLED": "true"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_TASKS_ENABLED": "true", "DISCORD_TASKS_CHANNEL_ID": "999"})
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "DISCORD_TASKS_ENABLED": "true",
                "DISCORD_TASKS_CHANNEL_ID": "300",
                "DISCORD_TASKS_PROFILE": "family",
                "DISCORD_TASKS_STATE_PATH": "/tmp/tasks-state.json",
            }
        )
        self.assertTrue(settings.tasks_enabled)
        self.assertEqual(settings.tasks_channel_id, 300)
        self.assertEqual(settings.tasks_profile, "family")
        self.assertEqual(str(settings.tasks_state_path), "/tmp/tasks-state.json")

    def test_tasks_surface_rejects_unknown_profile(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "DISCORD_TASKS_ENABLED": "true",
                    "DISCORD_TASKS_CHANNEL_ID": "300",
                    "DISCORD_TASKS_PROFILE": "clinic",
                }
            )

    def test_supplies_surface_is_disabled_by_default(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        self.assertFalse(settings.supplies_enabled)
        self.assertIsNone(settings.supplies_channel_id)
        self.assertEqual(settings.supplies_profile, "main")
        self.assertEqual(settings.supplies_collection_id, "")

    def test_supplies_surface_requires_allowed_channel_when_enabled(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_SUPPLIES_ENABLED": "true"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {**BASE_ENV, "DISCORD_SUPPLIES_ENABLED": "true", "DISCORD_SUPPLIES_CHANNEL_ID": "999"}
            )
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "DISCORD_SUPPLIES_ENABLED": "true",
                "DISCORD_SUPPLIES_CHANNEL_ID": "300",
                "DISCORD_SUPPLIES_PROFILE": "family",
                "DISCORD_SUPPLIES_STATE_PATH": "/tmp/supplies-state.json",
                "DISCORD_SUPPLIES_COLLECTION_ID": "family:supplies",
            }
        )
        self.assertTrue(settings.supplies_enabled)
        self.assertEqual(settings.supplies_channel_id, 300)
        self.assertEqual(settings.supplies_profile, "family")
        self.assertEqual(str(settings.supplies_state_path), "/tmp/supplies-state.json")
        self.assertEqual(settings.supplies_collection_id, "family:supplies")

    def test_supplies_surface_rejects_unknown_profile(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "DISCORD_SUPPLIES_ENABLED": "true",
                    "DISCORD_SUPPLIES_CHANNEL_ID": "300",
                    "DISCORD_SUPPLIES_PROFILE": "clinic",
                }
            )

    def test_document_inbox_is_disabled_by_default(self) -> None:
        settings = Settings.from_env(BASE_ENV)
        self.assertFalse(settings.inbox_enabled)
        self.assertIsNone(settings.inbox_channel_id)
        self.assertEqual(settings.paperless_base_url, "")
        self.assertEqual(settings.paperless_api_token, "")

    def test_memos_capture_requires_allowed_channel_when_enabled(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_MEMOS_ENABLED": "true"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_MEMOS_ENABLED": "true", "DISCORD_MEMOS_CHANNEL_ID": "999"})
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "DISCORD_MEMOS_ENABLED": "true",
                "DISCORD_MEMOS_CHANNEL_ID": "300",
            }
        )
        self.assertTrue(settings.memos_enabled)
        self.assertEqual(settings.memos_channel_id, 300)

    def test_document_inbox_requires_channel_and_paperless_credentials(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "DISCORD_INBOX_ENABLED": "true"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "DISCORD_INBOX_ENABLED": "true",
                    "DISCORD_INBOX_CHANNEL_ID": "999",
                }
            )
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "DISCORD_INBOX_ENABLED": "true",
                    "DISCORD_INBOX_CHANNEL_ID": "300",
                    "PAPERLESS_BASE_URL": "http://paperless:8000",
                }
            )
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "DISCORD_INBOX_ENABLED": "true",
                "DISCORD_INBOX_CHANNEL_ID": "300",
                "DISCORD_INBOX_STATE_PATH": "/tmp/inbox-state.json",
                "PAPERLESS_BASE_URL": "http://paperless:8000",
                "PAPERLESS_API_TOKEN": "not-a-real-token",
                "PAPERLESS_PUBLIC_URL": "https://paperless.example",
                "PAPERLESS_INBOX_MAX_ATTACHMENT_MB": "12",
            }
        )
        self.assertTrue(settings.inbox_enabled)
        self.assertEqual(settings.inbox_channel_id, 300)
        self.assertEqual(str(settings.inbox_state_path), "/tmp/inbox-state.json")
        self.assertEqual(settings.paperless_base_url, "http://paperless:8000")
        self.assertEqual(settings.paperless_api_token, "not-a-real-token")
        self.assertEqual(settings.paperless_max_attachment_mb, 12)

    def test_memos_search_requires_a_governor_api_token(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "MEMOS_SEARCH_ENABLED": "true"})
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "MEMOS_SEARCH_ENABLED": "true",
                "GOVERNOR_API_TOKEN": "not-a-real-secret",
            }
        )
        self.assertEqual(settings.governor_api_token, "not-a-real-secret")

    def test_governor_api_token_can_be_loaded_from_a_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "governor-api-token"
            token_file.write_text("file-secret\n", encoding="utf-8")
            settings = Settings.from_env(
                {
                    **BASE_ENV,
                    "MEMOS_SEARCH_ENABLED": "true",
                    "GOVERNOR_API_TOKEN_FILE": str(token_file),
                }
            )
        self.assertEqual(settings.governor_api_token, "file-secret")


class AccessPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AccessPolicy(100, frozenset({200}), frozenset({300}))

    def test_allows_exact_match(self) -> None:
        self.assertTrue(self.policy.allows(100, 300, 200))

    def test_rejects_wrong_boundary(self) -> None:
        self.assertFalse(self.policy.allows(999, 300, 200))
        self.assertFalse(self.policy.allows(100, 999, 200))
        self.assertFalse(self.policy.allows(100, 300, 999))
        self.assertFalse(self.policy.allows(None, 300, 200))


if __name__ == "__main__":
    unittest.main()
