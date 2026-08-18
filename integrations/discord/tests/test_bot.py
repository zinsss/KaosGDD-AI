from types import SimpleNamespace
import unittest

from kaos_governor_discord.bot import GovernorBot


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


if __name__ == "__main__":
    unittest.main()
