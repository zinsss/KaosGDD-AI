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
            {**BASE_ENV, "MAIL_ORGANIZER_ENABLED": "true", "MAIL_ORGANIZER_DISCORD_CHANNEL_ID": "300"}
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
