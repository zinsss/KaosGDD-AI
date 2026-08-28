from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from kaos_governor.mail import MailMessage
from kaos_governor_discord import bot as bot_module
from kaos_governor_discord.bot import GovernorBot
from kaos_governor_discord.maintenance import MaintenanceReport, MaintenanceTarget


class FakeServiceStatus:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.last_results = {"kaosbrain": object(), "kaosgovernor": object()}

    async def ensure_message(self) -> None:
        self.ensure_calls += 1


class GovernorBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_service_status_surface_updates_messages_and_returns_count(self) -> None:
        service_status = FakeServiceStatus()
        bot = SimpleNamespace(discord_service_status=service_status)

        checked = await GovernorBot._refresh_service_status_surface(bot)  # type: ignore[arg-type]

        self.assertEqual(checked, 2)
        self.assertEqual(service_status.ensure_calls, 1)

    async def test_refresh_service_status_surface_handles_disabled_surface(self) -> None:
        bot = SimpleNamespace(discord_service_status=None)

        checked = await GovernorBot._refresh_service_status_surface(bot)  # type: ignore[arg-type]

        self.assertEqual(checked, 0)

    async def test_maintenance_reminder_sends_openclaw_renewal_once(self) -> None:
        class FakeChannel:
            def __init__(self) -> None:
                self.sent: list[str] = []

            async def send(self, content, **_kwargs):
                self.sent.append(content)

        async def fake_collect():
            return [
                MaintenanceReport(
                    MaintenanceTarget("kaosbrain", "ssh", "zin@kaosbrain", "/repo"),
                    True,
                    {
                        "openclaw_configured": "yes",
                        "openclaw_primary_model": "openai/gpt-5.6-sol",
                        "openclaw_last_touched": "2026-08-10T09:00:00+09:00",
                    },
                )
            ]

        original_collect = bot_module.collect_maintenance_reports
        bot_module.collect_maintenance_reports = fake_collect
        try:
            with tempfile.TemporaryDirectory() as temporary:
                channel = FakeChannel()
                bot = SimpleNamespace(
                    settings=SimpleNamespace(
                        system_channel_id=1536016952521261190,
                        service_status_state_path=Path(temporary) / "status.json",
                    ),
                    get_channel=lambda _channel_id: channel,
                    fetch_channel=None,
                    text_notifications=SimpleNamespace(
                        config=SimpleNamespace(enabled=True),
                        notify=Mock(),
                    ),
                )

                first = await GovernorBot._send_due_maintenance_reminders(bot)  # type: ignore[arg-type]
                second = await GovernorBot._send_due_maintenance_reminders(bot)  # type: ignore[arg-type]

        finally:
            bot_module.collect_maintenance_reports = original_collect

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(len(channel.sent), 1)
        self.assertIn("KaosAI ChatGPT renewal", channel.sent[0])
        bot.text_notifications.notify.assert_called_once()
        mirrored = bot.text_notifications.notify.call_args.args[0]
        self.assertEqual(mirrored.category, "maintenance")

    async def test_new_mail_watch_alert_omits_preview_and_attachments(self) -> None:
        channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=501)))
        mirrored = []

        async def mail_channel():
            return channel

        async def queue_text_notification(notification):
            mirrored.append(notification)
            return True

        bot = SimpleNamespace(
            _mail_channel=mail_channel,
            _queue_text_notification=queue_text_notification,
            mail_poller=SimpleNamespace(config=SimpleNamespace(max_attachment_bytes=1024)),
        )
        mail = MailMessage(
            mailbox="세무사",
            uid=42,
            sender="sender@example.test",
            subject="Tax document arrived",
            preview="Sensitive body must remain in Governor.",
            attachments=(),
            received_at="2026-08-28 18:10 KST",
        )

        await GovernorBot._send_mail_summary(bot, mail)  # type: ignore[arg-type]

        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored[0].category, "mail")
        self.assertIn("Tax document arrived", mirrored[0].message)
        self.assertNotIn("Sensitive body", mirrored[0].message)


if __name__ == "__main__":
    unittest.main()
