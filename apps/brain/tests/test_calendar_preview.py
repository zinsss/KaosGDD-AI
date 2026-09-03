from __future__ import annotations

import unittest
from importlib.util import find_spec

from kaos_brain.config import Settings

AIOHTTP_AVAILABLE = find_spec("aiohttp") is not None

if AIOHTTP_AVAILABLE:
    from aiohttp.test_utils import TestClient, TestServer
    from kaos_brain.calendar_preview import BrainCalendarPreviewServer, validate_calendar_preview_request


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSBRAIN_CALENDAR_PREVIEW_API_TOKEN": "calendar-token",
}


def preview_payload() -> dict:
    return {
        "text": "연차 / 12:30 메롱",
        "date": "2026-09-03",
        "profile": "family",
        "grammarEvents": [
            {
                "title": "연차",
                "allDay": True,
                "startDate": "2026-09-03",
                "startTime": "",
                "endDate": "2026-09-03",
                "endTime": "",
            }
        ],
    }


class FakeKaosAI:
    def __init__(self) -> None:
        self.requests = []

    async def preview_calendar_events(self, request):
        self.requests.append(request)
        return [
            {
                "title": "메롱",
                "allDay": False,
                "startDate": "2026-09-03",
                "startTime": "12:30",
                "endDate": "2026-09-03",
                "endTime": "13:30",
            }
        ]


@unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for BrainCalendarPreviewServer tests")
class BrainCalendarPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = BrainCalendarPreviewServer(
            Settings.from_env(
                {
                    **BASE_ENV,
                    "KAOSAI_ENABLED": "true",
                    "KAOSAI_PROVIDER": "openclaw",
                    "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                    "KAOSAI_API_TOKEN": "gateway-token",
                }
            )
        )
        self.kaosai = FakeKaosAI()
        self.server.kaosai = self.kaosai  # type: ignore[assignment]
        self.client = TestClient(TestServer(self._app()))
        await self.client.start_server()

    def _app(self):
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/internal/calendar/smart-events/preview", self.server.preview)
        return app

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_preview_requires_bearer_token(self) -> None:
        response = await self.client.post("/internal/calendar/smart-events/preview", json=preview_payload())

        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "kaosbrain_calendar_preview_unauthorized")

    async def test_preview_returns_ai_events_without_writing(self) -> None:
        response = await self.client.post(
            "/internal/calendar/smart-events/preview",
            headers={"Authorization": "Bearer calendar-token"},
            json=preview_payload(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "ai")
        self.assertEqual(payload["events"][0]["title"], "메롱")
        self.assertEqual(self.kaosai.requests[0]["text"], "연차 / 12:30 메롱")

    async def test_preview_reports_disabled_openai(self) -> None:
        disabled = BrainCalendarPreviewServer(Settings.from_env(BASE_ENV))
        client = TestClient(TestServer(self._app_for(disabled)))
        await client.start_server()
        try:
            response = await client.post(
                "/internal/calendar/smart-events/preview",
                headers={"Authorization": "Bearer calendar-token"},
                json=preview_payload(),
            )

            self.assertEqual(response.status, 503)
            self.assertEqual((await response.json())["error"], "kaosbrain_openai_disabled")
        finally:
            await client.close()

    def _app_for(self, server):
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/internal/calendar/smart-events/preview", server.preview)
        return app


@unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for calendar preview validation tests")
class BrainCalendarPreviewValidationTests(unittest.TestCase):
    def test_validate_accepts_expected_payload(self) -> None:
        self.assertEqual(validate_calendar_preview_request(preview_payload()), "")

    def test_validate_rejects_non_family_profile(self) -> None:
        payload = preview_payload()
        payload["profile"] = "personal"

        self.assertEqual(validate_calendar_preview_request(payload), "calendar_preview_family_profile_required")


if __name__ == "__main__":
    unittest.main()
