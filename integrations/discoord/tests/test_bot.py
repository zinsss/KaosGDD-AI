from types import SimpleNamespace
from datetime import date, datetime, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from kaos_governor.mail import MailMessage
from kaos_governor.daily_digest import KST
from kaosdiscoord import bot as bot_module
from kaosdiscoord.bot import GovernorBot
from kaosdiscoord.maintenance import MaintenanceReport, MaintenanceTarget


class FakeServiceStatus:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.last_results = {"kaosbrain": object(), "kaosgovernor": object()}

    async def ensure_message(self) -> None:
        self.ensure_calls += 1


class GovernorBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_mode_never_starts_inline_pushover_delivery(self) -> None:
        notifications = SimpleNamespace(
            config=SimpleNamespace(delivery_mode="worker", poll_seconds=5),
            deliver_pending=Mock(),
        )
        bot = SimpleNamespace(
            text_notifications=notifications,
            is_closed=Mock(return_value=False),
        )

        await GovernorBot._text_notification_loop(bot)  # type: ignore[arg-type]

        notifications.deliver_pending.assert_not_called()

    async def test_worker_owned_mail_loop_performs_no_discord_polling(self) -> None:
        poller = SimpleNamespace(
            config=SimpleNamespace(owner="worker"),
            scan=Mock(),
        )
        bot = SimpleNamespace(mail_poller=poller)

        await GovernorBot._mail_loop(bot)  # type: ignore[arg-type]

        poller.scan.assert_not_called()

    async def test_worker_owned_fax_loop_performs_no_discord_polling(self) -> None:
        transport = SimpleNamespace(cycle=AsyncMock())
        bot = SimpleNamespace(
            discord_fax=transport,
            fax_service=SimpleNamespace(config=SimpleNamespace(owner="worker")),
        )

        await GovernorBot._fax_loop(bot)  # type: ignore[arg-type]

        transport.cycle.assert_not_awaited()

    async def test_daily_digest_posts_simple_morning_and_event_watch_alerts(self) -> None:
        channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=701)))
        daily_digest = SimpleNamespace(
            is_due=Mock(return_value=True),
            build=Mock(
                return_value=(
                    "# 2026.08.29(Sat)\n* 🌧️ rain 23-30°C\n\n"
                    "### Events\n- Christmas\n\n### Tasks\n-"
                )
            ),
            record_sent=Mock(),
            weather_url=Mock(return_value="https://kaosgdd.net/#/calendar?weather=2026-08-29"),
        )
        mirrored = []

        async def queue_text_notification(notification):
            mirrored.append(notification)
            return True

        bot = SimpleNamespace(
            daily_digest=daily_digest,
            settings=SimpleNamespace(system_channel_id=301),
            get_channel=lambda _channel_id: channel,
            fetch_channel=AsyncMock(return_value=channel),
            _queue_text_notification=queue_text_notification,
        )
        now = datetime(2026, 8, 29, 7, 0, tzinfo=KST)

        published = await GovernorBot._publish_daily_digest(bot, now)  # type: ignore[arg-type]

        self.assertTrue(published)
        channel.send.assert_awaited_once()
        view = channel.send.await_args.kwargs["view"]
        self.assertEqual([item.label for item in view.children], ["Weather", "Bible", "Quote", "Close"])
        self.assertEqual(view.children[0].url, "https://kaosgdd.net/#/calendar?weather=2026-08-29")
        self.assertEqual(mirrored[0].category, "daily")
        self.assertEqual(mirrored[0].key, "daily:2026-08-29")
        self.assertEqual(mirrored[0].title, "")
        self.assertEqual(mirrored[0].message, "Good Morning.")
        self.assertEqual(mirrored[0].priority, 0)
        self.assertEqual(len(mirrored), 2)
        self.assertEqual(mirrored[1].message, "Today. Christmas.")
        self.assertEqual(mirrored[1].priority, 0)
        daily_digest.record_sent.assert_called_once_with(date(2026, 8, 29), message_id=701)

    async def test_worker_owned_digest_only_transports_pending_publication(self) -> None:
        channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=702)))
        daily_digest = SimpleNamespace(
            pending_publication=Mock(
                return_value={
                    "date": "2026-08-29",
                    "content": "# 2026.08.29(Sat)\n### Events\n-",
                }
            ),
            record_published=Mock(),
            weather_url=Mock(return_value="https://kaosgdd.net/#/calendar?weather=2026-08-29"),
        )
        bot = SimpleNamespace(
            daily_digest=daily_digest,
            settings=SimpleNamespace(system_channel_id=301),
            get_channel=lambda _channel_id: channel,
            fetch_channel=AsyncMock(return_value=channel),
            _daily_digest_view_message_id=0,
        )

        published = await GovernorBot._publish_pending_daily_digest(bot)  # type: ignore[arg-type]

        self.assertTrue(published)
        channel.send.assert_awaited_once()
        daily_digest.record_published.assert_called_once_with(date(2026, 8, 29), message_id=702)
        self.assertEqual(bot._daily_digest_view_message_id, 702)

    async def test_daily_digest_cycle_edits_message_with_persistent_controls(self) -> None:
        response = SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock())
        interaction = SimpleNamespace(
            message=SimpleNamespace(content="# 2026.08.29(Sat)\n### 일일 성경 말씀\nFirst"),
            response=response,
        )
        daily_digest = SimpleNamespace(
            cycle_content=Mock(return_value="# 2026.08.29(Sat)\n### 일일 성경 말씀\nSecond"),
            weather_url=Mock(return_value="https://kaosgdd.net/#/calendar?weather=2026-08-29"),
        )
        bot = SimpleNamespace(daily_digest=daily_digest)

        await GovernorBot._cycle_daily_content(bot, interaction, "bible")  # type: ignore[arg-type]

        daily_digest.cycle_content.assert_called_once()
        response.edit_message.assert_awaited_once()
        self.assertEqual(
            [item.label for item in response.edit_message.await_args.kwargs["view"].children],
            ["Weather", "Bible", "Quote", "Close"],
        )

    async def test_daily_digest_restore_replaces_controls_on_existing_message(self) -> None:
        message = SimpleNamespace(edit=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        bot = SimpleNamespace(
            daily_digest=SimpleNamespace(
                last_sent_day=Mock(return_value=date(2026, 8, 29)),
                weather_url=Mock(return_value="https://kaosgdd.net/#/calendar?weather=2026-08-29"),
            ),
            settings=SimpleNamespace(system_channel_id=301),
            add_view=Mock(),
            get_channel=lambda _channel_id: channel,
            fetch_channel=AsyncMock(return_value=channel),
            _daily_digest_view_message_id=0,
        )

        await GovernorBot._restore_daily_digest_view(bot, 701)  # type: ignore[arg-type]

        bot.add_view.assert_called_once()
        channel.fetch_message.assert_awaited_once_with(701)
        message.edit.assert_awaited_once()
        view = message.edit.await_args.kwargs["view"]
        self.assertEqual(view.children[0].url, "https://kaosgdd.net/#/calendar?weather=2026-08-29")
        self.assertEqual(bot._daily_digest_view_message_id, 701)

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
        self.assertIn("KaosBrain-OpenAI ChatGPT renewal", channel.sent[0])
        bot.text_notifications.notify.assert_called_once()
        mirrored = bot.text_notifications.notify.call_args.args[0]
        self.assertEqual(mirrored.category, "maintenance")
        self.assertEqual(mirrored.title, "")
        self.assertEqual(mirrored.message, "KaosBrain auth renewal.")
        self.assertEqual(mirrored.priority, 1)

    async def test_actionable_fresh_maintenance_report_sends_simple_watch_alert_once(self) -> None:
        class FakeChannel:
            def __init__(self) -> None:
                self.sent: list[str] = []

            async def send(self, content, **_kwargs):
                self.sent.append(content)

        async def fake_collect():
            return [
                MaintenanceReport(
                    MaintenanceTarget("kaosgdd", "local", "", "/repo"),
                    True,
                    {
                        "os_updates": "2",
                        "docker_package_updates": "0",
                        "docker_unhealthy": "0",
                        "reboot_required": "no",
                    },
                    collected_at=datetime.now(timezone.utc).isoformat(),
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
        self.assertIn("System maintenance required", channel.sent[0])
        mirrored = bot.text_notifications.notify.call_args.args[0]
        self.assertEqual(mirrored.title, "")
        self.assertEqual(mirrored.message, "System maintenance required.")
        self.assertEqual(mirrored.priority, 1)

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
        self.assertEqual(mirrored[0].message, "Mail received.")
        self.assertEqual(mirrored[0].priority, 0)
        self.assertNotIn("Tax document arrived", mirrored[0].message)
        self.assertNotIn("Sensitive body", mirrored[0].message)


if __name__ == "__main__":
    unittest.main()
