from pathlib import Path
import tempfile
import unittest
import urllib.parse
from unittest import mock

from kaos_governor.notifications import (
    NotificationError,
    PushoverClient,
    PushoverConfig,
    TextNotification,
    TextNotificationService,
)


class NotificationTests(unittest.TestCase):
    def config(self, root: Path, *, enabled: bool = True) -> PushoverConfig:
        return PushoverConfig(
            enabled=enabled,
            state_path=root / "pushover.json",
            app_token="app-secret" if enabled else "",
            user_key="user-secret" if enabled else "",
            priority=1,
            timeout_seconds=10,
            poll_seconds=5,
        )

    def notification(self, **values) -> TextNotification:
        return TextNotification(
            key=values.get("key", "fax:event-1"),
            category=values.get("category", "fax"),
            title=values.get("title", "KaosGDD Fax"),
            message=values.get("message", "Fax received.\n: from 07079664986"),
        )

    def test_enabled_configuration_requires_file_backed_credentials(self) -> None:
        with self.assertRaisesRegex(NotificationError, "PUSHOVER_APP_TOKEN"):
            PushoverConfig.from_env({"PUSHOVER_ENABLED": "true"})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_token = root / "app-token"
            user_key = root / "user-key"
            app_token.write_text("app-secret\n", encoding="utf-8")
            user_key.write_text("user-secret\n", encoding="utf-8")
            config = PushoverConfig.from_env(
                {
                    "PUSHOVER_ENABLED": "true",
                    "PUSHOVER_APP_TOKEN_FILE": str(app_token),
                    "PUSHOVER_USER_KEY_FILE": str(user_key),
                    "PUSHOVER_PRIORITY": "1",
                }
            )

        self.assertTrue(config.enabled)
        self.assertEqual(config.app_token, "app-secret")
        self.assertEqual(config.user_key, "user-secret")

        with self.assertRaisesRegex(NotificationError, "between 0 and 1"):
            PushoverConfig.from_env(
                {
                    "PUSHOVER_ENABLED": "true",
                    "PUSHOVER_APP_TOKEN": "app-secret",
                    "PUSHOVER_USER_KEY": "user-secret",
                    "PUSHOVER_PRIORITY": "2",
                }
            )

    def test_client_posts_high_priority_text_only_alert(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"status":1,"request":"request-id"}'

        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary))
            urlopen = mock.Mock(return_value=Response())
            client = PushoverClient(config, urlopen=urlopen)

            client.send(self.notification())

        request = urlopen.call_args.args[0]
        payload = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, PushoverClient.API_URL)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)
        self.assertEqual(payload["token"], ["app-secret"])
        self.assertEqual(payload["user"], ["user-secret"])
        self.assertEqual(payload["title"], ["KaosGDD Fax"])
        self.assertEqual(payload["priority"], ["1"])
        self.assertIn("07079664986", payload["message"][0])
        self.assertNotIn("file", payload)

    def test_client_omits_optional_title_for_minimal_watch_alert(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"status":1}'

        with tempfile.TemporaryDirectory() as temporary:
            urlopen = mock.Mock(return_value=Response())
            client = PushoverClient(self.config(Path(temporary)), urlopen=urlopen)
            client.send(self.notification(title="", message="Good Morning."))

        payload = urllib.parse.parse_qs(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertNotIn("title", payload)
        self.assertEqual(payload["message"], ["Good Morning."])

    def test_notify_delivers_immediately_and_deduplicates_durably(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary))
            client = mock.Mock()
            service = TextNotificationService(config, client=client)

            first = service.notify(
                self.notification(message="## Fax received.\n**From** 07079664986")
            )
            duplicate = service.notify(self.notification())
            status = service.status()

        self.assertTrue(first)
        self.assertFalse(duplicate)
        client.send.assert_called_once()
        delivered = client.send.call_args.args[0]
        self.assertEqual(delivered.message, "Fax received.\nFrom 07079664986")
        self.assertEqual(status["pendingCount"], 0)
        self.assertEqual(status["deliveredCount"], 1)
        self.assertFalse(status["tasksMirrored"])

    def test_failed_delivery_stays_pending_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary))
            client = mock.Mock()
            client.send.side_effect = [NotificationError("offline"), None]
            service = TextNotificationService(config, client=client)

            with self.assertRaisesRegex(NotificationError, "pending_delivery"):
                service.notify(self.notification(category="mail", key="mail:event-1"))
            pending = service.status()
            delivered = service.deliver_pending()
            final = service.status()

        self.assertEqual(pending["pendingCount"], 1)
        self.assertIn("offline", pending["lastError"])
        self.assertEqual(delivered, 1)
        self.assertEqual(final["pendingCount"], 0)
        self.assertEqual(final["deliveredCount"], 1)
        self.assertEqual(final["lastError"], "")

    def test_tasks_are_not_an_allowed_mirror_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = TextNotificationService(self.config(Path(temporary)))
            with self.assertRaisesRegex(NotificationError, "category_not_mirrored"):
                service.enqueue(self.notification(category="task", key="task:event-1"))

    def test_empty_title_is_allowed_for_minimal_watch_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = mock.Mock()
            service = TextNotificationService(self.config(Path(temporary)), client=client)

            service.notify(self.notification(title="", message="Fax received."))

        delivered = client.send.call_args.args[0]
        self.assertEqual(delivered.title, "")
        self.assertEqual(delivered.message, "Fax received.")

    def test_disabled_service_does_not_create_an_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary), enabled=False)
            service = TextNotificationService(config)

            created = service.notify(self.notification())

            self.assertFalse(created)
            self.assertFalse(config.state_path.exists())


if __name__ == "__main__":
    unittest.main()
