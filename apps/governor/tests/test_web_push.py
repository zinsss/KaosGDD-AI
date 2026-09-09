from pathlib import Path
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from kaos_governor.notifications import TextNotification
from kaos_governor.web_push import (
    WebPushClient,
    WebPushConfig,
    WebPushDeliveryError,
    WebPushError,
    WebPushService,
    WebPushSubscriptionStore,
)


def private_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode("ascii")


def subscription(endpoint: str = "https://web.push.apple.com/QWERTY") -> dict[str, object]:
    return {
        "endpoint": endpoint,
        "expirationTime": None,
        "keys": {"p256dh": "AQIDBA", "auth": "BQYHCA"},
    }


class WebPushTests(unittest.TestCase):
    def config(self, root: Path) -> WebPushConfig:
        return WebPushConfig(
            enabled=True,
            subscriptions_path=root / "subscriptions.json",
            outbox_path=root / "outbox.json",
            private_key=private_key_pem(),
            subject="mailto:admin@kaosgdd.net",
        )

    def test_config_derives_public_key_and_requires_valid_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            key_path = Path(temporary) / "vapid.pem"
            key_path.write_text(private_key_pem(), encoding="utf-8")
            config = WebPushConfig.from_env(
                {
                    "WEB_PUSH_ENABLED": "true",
                    "WEB_PUSH_VAPID_PRIVATE_KEY_FILE": str(key_path),
                    "WEB_PUSH_VAPID_SUBJECT": "mailto:admin@kaosgdd.net",
                }
            )
        self.assertTrue(config.public_key().startswith("B"))
        self.assertEqual(len(config.public_key()), 87)
        self.assertEqual(len(config.encoded_private_key()), 43)
        with self.assertRaisesRegex(WebPushError, "VAPID_SUBJECT"):
            WebPushConfig.from_env(
                {
                    "WEB_PUSH_ENABLED": "true",
                    "WEB_PUSH_VAPID_PRIVATE_KEY": private_key_pem(),
                    "WEB_PUSH_VAPID_SUBJECT": "admin",
                }
            )

    def test_publisher_config_does_not_load_vapid_private_key(self) -> None:
        config = WebPushConfig.publisher_from_env(
            {
                "WEB_PUSH_ENABLED": "true",
                "WEB_PUSH_SUBSCRIPTIONS_PATH": "/tmp/subscriptions.json",
                "WEB_PUSH_OUTBOX_PATH": "/tmp/outbox.json",
            }
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.private_key, "")
        self.assertEqual(config.subject, "")

    def test_subscription_endpoint_is_restricted_to_push_providers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = WebPushSubscriptionStore(Path(temporary) / "subscriptions.json")
            with self.assertRaisesRegex(WebPushError, "endpoint_not_allowed"):
                store.upsert(subscription("https://example.com/callback"))
            with self.assertRaisesRegex(WebPushError, "endpoint_invalid"):
                store.upsert(subscription("http://web.push.apple.com/insecure"))

    def test_delivery_uses_generic_payload_and_never_original_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary))
            sender = mock.Mock()
            service = WebPushService(config, client=WebPushClient(config, sender=sender))
            registered = service.subscribe(subscription())
            created = service.enqueue(
                TextNotification(
                    key="fax:secret-1",
                    category="fax",
                    title="Patient name",
                    message="Sensitive fax body and phone number",
                    priority=1,
                )
            )
            delivered = service.deliver_pending()
            status = service.status()

        self.assertTrue(registered["id"])
        self.assertTrue(created)
        self.assertEqual(delivered, 1)
        sender.assert_called_once()
        private_key = sender.call_args.kwargs["vapid_private_key"]
        self.assertEqual(len(private_key), 43)
        self.assertNotIn("BEGIN", private_key)
        payload = sender.call_args.kwargs["data"]
        self.assertIn("Fax needs attention.", payload)
        self.assertNotIn("Patient name", payload)
        self.assertNotIn("Sensitive fax", payload)
        self.assertEqual(status["pendingCount"], 0)

    def test_ai_task_delivery_is_generic_and_opens_ai_task_archive(self) -> None:
        payload = WebPushService._payload("ai-task:ait-secret:completed", "ai_task", 0)
        failed_payload = WebPushService._payload("ai-task:ait-secret:failed", "ai_task_failed", 1)

        self.assertEqual(payload["body"], "AI Task is ready.")
        self.assertEqual(payload["url"], "/#/ai-tasks")
        self.assertEqual(failed_payload["body"], "AI Task needs attention.")
        self.assertEqual(failed_payload["url"], "/#/ai-tasks")
        self.assertNotIn("ait-secret", str(payload))

    def test_expired_subscription_is_removed_without_blocking_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary))
            client = mock.Mock()
            client.send.side_effect = WebPushDeliveryError("gone", 410)
            service = WebPushService(config, client=client)
            registered = service.subscribe(subscription())
            service.enqueue(
                TextNotification(key="mail:1", category="mail", title="", message="Mail")
            )
            delivered = service.deliver_pending()

            self.assertEqual(delivered, 1)
            self.assertIsNone(service.store.get(str(registered["id"])))


if __name__ == "__main__":
    unittest.main()
