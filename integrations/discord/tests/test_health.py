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


if __name__ == "__main__":
    unittest.main()
