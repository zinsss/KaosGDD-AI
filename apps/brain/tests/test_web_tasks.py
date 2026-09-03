from __future__ import annotations

import unittest
from importlib.util import find_spec

from kaos_brain.kaos_ai import (
    KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT,
    parse_official_web_plan_response,
    parse_official_web_summary_response,
)
from kaos_brain.web_tasks import _extract_response_text, _extract_sources, validate_web_task_request

AIOHTTP_AVAILABLE = find_spec("aiohttp") is not None

if AIOHTTP_AVAILABLE:
    from aiohttp.test_utils import TestClient, TestServer
    from kaos_brain.config import Settings
    from kaos_brain.web_tasks import BrainWebTaskServer


BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_ID": "100",
    "DISCORD_ALLOWED_USER_IDS": "200",
    "DISCORD_BRAIN_CHANNEL_ID": "300",
    "KAOSBRAIN_AI_TASK_API_TOKEN": "ai-task-token",
    "KAOSBRAIN_OPENAI_API_KEY": "test-key",
}


@unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for BrainWebTaskServer tests")
class BrainWebTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = BrainWebTaskServer(Settings.from_env(BASE_ENV))
        self.client = TestClient(TestServer(self._app()))
        await self.client.start_server()

    def _app(self):
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/internal/ai-tasks/web/preview", self.server.preview)
        return app

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_preview_requires_bearer_token(self) -> None:
        response = await self.client.post("/internal/ai-tasks/web/preview", json={"prompt": "find source"})

        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"], "kaosbrain_ai_task_unauthorized")

    async def test_preview_requires_openai_key(self) -> None:
        self.server.settings = Settings.from_env({key: value for key, value in BASE_ENV.items() if key != "KAOSBRAIN_OPENAI_API_KEY"})

        response = await self.client.post(
            "/internal/ai-tasks/web/preview",
            headers={"Authorization": "Bearer ai-task-token"},
            json={"prompt": "find source"},
        )

        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "kaosbrain_web_search_not_configured")


class WebTaskValidationTests(unittest.TestCase):
    def test_validate_requires_prompt(self) -> None:
        self.assertEqual(validate_web_task_request({"prompt": ""}), "web_task_prompt_required")

    def test_extracts_text_and_sources_from_response_payload(self) -> None:
        payload = {
            "output": [
                {
                    "content": [
                        {
                            "text": "요약 결과",
                            "annotations": [{"title": "KDCA", "url": "https://www.kdca.go.kr/example"}],
                        }
                    ]
                }
            ]
        }

        self.assertEqual(_extract_response_text(payload), "요약 결과")
        self.assertEqual(_extract_sources(payload), [{"title": "KDCA", "url": "https://www.kdca.go.kr/example"}])

    def test_parses_official_web_plan_response(self) -> None:
        plan = parse_official_web_plan_response(
            '{"query":"인플루엔자 접종 계획","alternateQueries":["국가예방접종"],"preferredDomains":["kdca.go.kr"],"task":"summary","language":"ko"}',
            {"prompt": "공식 자료 찾아서 요약"},
        )

        self.assertEqual(plan["query"], "인플루엔자 접종 계획")
        self.assertEqual(plan["preferredDomains"], ["kdca.go.kr"])

    def test_parses_official_web_summary_response(self) -> None:
        result = parse_official_web_summary_response(
            '{"title":"요약","content":"본문","sources":[{"title":"KDCA","url":"https://www.kdca.go.kr/notice"}],"checkedAt":"2026-09-03","model":"default"}',
            {"checkedAt": "2026-09-03"},
        )

        self.assertEqual(result["title"], "요약")
        self.assertEqual(result["sources"], [{"title": "KDCA", "url": "https://www.kdca.go.kr/notice"}])

    def test_official_web_summary_prompt_requests_chart_note_guidance_for_benefits(self) -> None:
        self.assertIn("차트 기재 추천", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)
        self.assertIn("급여기준", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)
        self.assertIn("Do not invent patient facts", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
