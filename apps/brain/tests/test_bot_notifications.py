from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_brain.bot import BrainBot


class BrainNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_governor_fax_receipt_refreshes_active_control(self) -> None:
        brain = SimpleNamespace(
            settings=SimpleNamespace(
                guild_id=100,
                notification_channel_id=301,
                governor_bot_user_id=400,
            ),
            _ensure_active_control_message=AsyncMock(),
        )
        message = SimpleNamespace(
            author=SimpleNamespace(id=400, bot=True),
            guild=SimpleNamespace(id=100),
            channel=SimpleNamespace(id=301),
            content="Fax received.\n: from 07079664986",
        )

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        brain._ensure_active_control_message.assert_awaited_once_with()

    async def test_untrusted_bot_message_does_not_refresh_active_control(self) -> None:
        brain = SimpleNamespace(
            settings=SimpleNamespace(
                guild_id=100,
                notification_channel_id=301,
                governor_bot_user_id=400,
            ),
            _ensure_active_control_message=AsyncMock(),
        )
        message = SimpleNamespace(
            author=SimpleNamespace(id=401, bot=True),
            guild=SimpleNamespace(id=100),
            channel=SimpleNamespace(id=301),
            content="Fax received.",
        )

        await BrainBot.on_message(brain, message)  # type: ignore[arg-type]

        brain._ensure_active_control_message.assert_not_awaited()
