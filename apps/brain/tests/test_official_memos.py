from __future__ import annotations

import unittest
from importlib.util import find_spec

from kaos_brain.config import Settings
from kaos_brain.kaos_ai import parse_official_memo_response

AIOHTTP_AVAILABLE = find_spec("aiohttp") is not None

if AIOHTTP_AVAILABLE:
    from aiohttp.test_utils import TestClient, TestServer
    from kaos_brain.official_memos import BrainOfficialMemoServer, validate_official_memo_request


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSBRAIN_AI_TASK_API_TOKEN": "ai-task-token",
}


def preview_payload() -> dict:
    return {
        "prompt": "국가 인플루엔자 접종 계획 요약",
        "checkedAt": "2026-09-03",
        "source": {
            "type": "text",
            "title": "질병관리청 안내",
            "url": "https://example.go.kr/flu",
            "text": "2026-2027절기 인플루엔자 예방접종 공식 안내입니다.",
        },
    }


class FakeKaosAI:
    def __init__(self) -> None:
        self.requests = []

    async def preview_official_memo(self, request):
        self.requests.append(request)
        return {
            "title": "인플루엔자 접종 계획",
            "content": "# 인플루엔자 접종 계획\n\n- 공식 안내 요약",
            "sourceTitle": "질병관리청 안내",
            "sourceUrl": "https://example.go.kr/flu",
            "checkedAt": "2026-09-03",
        }


@unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for BrainOfficialMemoServer tests")
class BrainOfficialMemoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = BrainOfficialMemoServer(
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
        app.router.add_post("/internal/ai-tasks/official-doc-memo/preview", self.server.preview)
        return app

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_preview_requires_bearer_token(self) -> None:
        response = await self.client.post("/internal/ai-tasks/official-doc-memo/preview", json=preview_payload())

        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "kaosbrain_ai_task_unauthorized")

    async def test_preview_returns_memo_without_writing(self) -> None:
        response = await self.client.post(
            "/internal/ai-tasks/official-doc-memo/preview",
            headers={"Authorization": "Bearer ai-task-token"},
            json=preview_payload(),
        )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "ai")
        self.assertEqual(payload["memo"]["title"], "인플루엔자 접종 계획")
        self.assertEqual(self.kaosai.requests[0]["prompt"], "국가 인플루엔자 접종 계획 요약")


@unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for official memo validation tests")
class BrainOfficialMemoValidationTests(unittest.TestCase):
    def test_validate_accepts_expected_payload(self) -> None:
        self.assertEqual(validate_official_memo_request(preview_payload()), "")

    def test_validate_requires_source_text(self) -> None:
        payload = preview_payload()
        payload["source"] = {"title": "empty"}

        self.assertEqual(validate_official_memo_request(payload), "official_memo_source_text_required")


class OfficialMemoParserTests(unittest.TestCase):
    def test_parse_normalizes_memo(self) -> None:
        memo = parse_official_memo_response(
            '{"title":"제목","content":"본문","sourceTitle":"공식","sourceUrl":"https://example.go.kr","checkedAt":"2026-09-03"}',
            preview_payload(),
        )

        self.assertEqual(memo["title"], "제목")
        self.assertTrue(str(memo["content"]).startswith("# 제목"))


if __name__ == "__main__":
    unittest.main()
