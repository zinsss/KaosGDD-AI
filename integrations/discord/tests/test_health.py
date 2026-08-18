from types import SimpleNamespace
import unittest

from aiohttp.test_utils import TestClient, TestServer
from kaos_governor.memos import Memo, MemoSearchResult, MemosError
from kaos_governor_discord.health import HealthServer


class StubMemos:
    def __init__(self) -> None:
        self.config = SimpleNamespace(enabled=True)
        self.search_calls = []
        self.get_calls = []

    def search(self, query, tags, limit):
        self.search_calls.append((query, tags, limit))
        memo = Memo("memos/42", "Complete memo body", ("server",), "created", "updated", "PRIVATE", True)
        return [MemoSearchResult(memo, "Complete memo body")]

    def get(self, name):
        self.get_calls.append(name)
        if name == "memos/missing":
            raise MemosError("memos_not_found", upstream_status=404)
        return Memo(name, "Current memo", (), "created", "updated", "PRIVATE", False)


class HealthServerToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.memos = StubMemos()
        server = HealthServer(
            "127.0.0.1",
            8097,
            lambda: {"discordReady": True},
            governor_api_token="governor-secret",
            memos=self.memos,
        )
        self.client = TestClient(TestServer(server.application()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_health_does_not_require_tool_credentials(self) -> None:
        response = await self.client.get("/health")
        self.assertEqual(response.status, 200)

    async def test_ready_requires_startup_complete_when_reported(self) -> None:
        server = HealthServer(
            "127.0.0.1",
            8097,
            lambda: {"discordReady": True, "startupComplete": False},
        )
        client = TestClient(TestServer(server.application()))
        await client.start_server()
        try:
            response = await client.get("/ready")
            payload = await response.json()
        finally:
            await client.close()

        self.assertEqual(response.status, 503)
        self.assertEqual(payload["status"], "not-ready")

    async def test_ready_accepts_completed_startup(self) -> None:
        server = HealthServer(
            "127.0.0.1",
            8097,
            lambda: {"discordReady": True, "startupComplete": True},
        )
        client = TestClient(TestServer(server.application()))
        await client.start_server()
        try:
            response = await client.get("/ready")
            payload = await response.json()
        finally:
            await client.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ready")

    async def test_ready_defaults_startup_complete_for_older_status_providers(self) -> None:
        response = await self.client.get("/ready")
        payload = await response.json()

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ready")

    async def test_search_requires_the_governor_bearer_token(self) -> None:
        response = await self.client.post("/api/v1/memos/search", json={"query": "printer"})
        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "governor_api_unauthorized")

    async def test_search_returns_normalized_live_results(self) -> None:
        response = await self.client.post(
            "/api/v1/memos/search",
            json={"query": "printer", "tags": ["server"], "limit": 3},
            headers={"Authorization": "Bearer governor-secret"},
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["source"], "memos-live")
        self.assertEqual(payload["results"][0]["name"], "memos/42")
        self.assertNotIn("content", payload["results"][0])
        self.assertEqual(self.memos.search_calls, [("printer", ["server"], 3)])

    async def test_get_returns_current_content_and_maps_not_found(self) -> None:
        headers = {"Authorization": "Bearer governor-secret"}
        response = await self.client.get("/api/v1/memos/42", headers=headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["memo"]["content"], "Current memo")
        self.assertEqual(self.memos.get_calls, ["memos/42"])

        response = await self.client.get("/api/v1/memos/missing", headers=headers)
        self.assertEqual(response.status, 404)
        self.assertEqual((await response.json())["error"], "memos_not_found")

    async def test_search_rejects_non_object_json(self) -> None:
        response = await self.client.post(
            "/api/v1/memos/search",
            json=["printer"],
            headers={"Authorization": "Bearer governor-secret"},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "invalid_request")

    async def test_calendar_settings_require_bearer_token(self) -> None:
        response = await self.client.get("/api/v1/settings/calendar")

        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "governor_api_unauthorized")

    async def test_calendar_settings_returns_defaults(self) -> None:
        response = await self.client.get(
            "/api/v1/settings/calendar",
            headers={"Authorization": "Bearer governor-secret"},
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["kind"], "calendar")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["settings"]["weatherLocation"], "Pohang, KR")
        self.assertEqual(payload["settings"]["publicHolidayProvider"], "imported")
        self.assertEqual(payload["settings"]["publicHolidayRegion"], "KR")

    async def test_calendar_settings_patch_updates_location_and_holidays(self) -> None:
        headers = {"Authorization": "Bearer governor-secret"}

        response = await self.client.patch(
            "/api/v1/settings/calendar",
            json={
                "weatherLocation": "Yeongdeok, KR",
                "publicHolidayProvider": "manual",
                "publicHolidayRegion": "kr",
                "publicHolidayCalendarUrl": "https://example.test/kr.ics",
            },
            headers=headers,
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["settings"]["weatherLocation"], "Yeongdeok, KR")
        self.assertEqual(payload["settings"]["publicHolidayProvider"], "manual")
        self.assertEqual(payload["settings"]["publicHolidayRegion"], "KR")
        self.assertEqual(payload["settings"]["publicHolidayCalendarUrl"], "https://example.test/kr.ics")

        response = await self.client.get("/api/v1/settings/calendar", headers=headers)
        self.assertEqual((await response.json())["settings"]["weatherLocation"], "Yeongdeok, KR")

    async def test_calendar_settings_patch_rejects_non_object_json(self) -> None:
        response = await self.client.patch(
            "/api/v1/settings/calendar",
            json=["Pohang"],
            headers={"Authorization": "Bearer governor-secret"},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
