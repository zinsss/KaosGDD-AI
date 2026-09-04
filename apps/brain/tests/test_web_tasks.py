from __future__ import annotations

import unittest
from importlib.util import find_spec

from kaos_brain.kaos_ai import (
    KAOSAI_OFFICIAL_WEB_PLAN_SYSTEM_PROMPT,
    KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT,
    parse_general_web_task_response,
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


class FakeKaosAI:
    def __init__(self) -> None:
        self.requests = []

    async def preview_web_task(self, request):
        self.requests.append(request)
        return {
            "title": "일반 웹 보조 맥락",
            "content": "OpenClaw web_search로 확인한 보조 내용",
            "sources": [{"title": "Example", "url": "https://example.com/source"}],
            "checkedAt": request["checkedAt"],
            "model": "openai/gpt-5.6-sol",
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

    async def test_preview_requires_configured_web_backend(self) -> None:
        self.server.settings = Settings.from_env({key: value for key, value in BASE_ENV.items() if key != "KAOSBRAIN_OPENAI_API_KEY"})

        response = await self.client.post(
            "/internal/ai-tasks/web/preview",
            headers={"Authorization": "Bearer ai-task-token"},
            json={"prompt": "find source"},
        )

        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "kaosbrain_web_search_not_configured")

    async def test_preview_falls_back_to_openclaw_web_search(self) -> None:
        self.server.settings = Settings.from_env(
            {
                **{key: value for key, value in BASE_ENV.items() if key != "KAOSBRAIN_OPENAI_API_KEY"},
                "KAOSAI_ENABLED": "true",
                "KAOSAI_PROVIDER": "openclaw",
                "KAOSAI_BASE_URL": "http://127.0.0.1:18789",
                "KAOSAI_API_TOKEN": "gateway-token",
            }
        )
        self.kaosai = FakeKaosAI()
        self.server.kaosai = self.kaosai  # type: ignore[assignment]

        response = await self.client.post(
            "/internal/ai-tasks/web/preview",
            headers={"Authorization": "Bearer ai-task-token"},
            json={"prompt": "공식 결과 바탕으로 일반 웹도 확인"},
        )

        payload = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["source"], "openclaw-web-search")
        self.assertEqual(payload["result"]["sources"][0]["url"], "https://example.com/source")
        self.assertEqual(self.kaosai.requests[0]["prompt"], "공식 결과 바탕으로 일반 웹도 확인")


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

    def test_parses_treatment_options_plan_response(self) -> None:
        plan = parse_official_web_plan_response(
            '{"query":"하지불안증후군 치료 옵션","alternateQueries":["restless legs syndrome treatment guideline"],"preferredDomains":["pubmed.ncbi.nlm.nih.gov","cks.nice.org.uk"],"task":"treatment_options","language":"ko"}',
            {"prompt": "하지불안증후군 치료 옵션 찾아줘"},
        )

        self.assertEqual(plan["task"], "treatment_options")
        self.assertEqual(plan["preferredDomains"], ["pubmed.ncbi.nlm.nih.gov", "cks.nice.org.uk"])

    def test_parses_official_web_summary_response(self) -> None:
        result = parse_official_web_summary_response(
            '{"title":"요약","content":"본문","sources":[{"title":"KDCA","url":"https://www.kdca.go.kr/notice"}],"checkedAt":"2026-09-03","model":"default"}',
            {"checkedAt": "2026-09-03"},
        )

        self.assertEqual(result["title"], "요약")
        self.assertEqual(result["sources"], [{"title": "KDCA", "url": "https://www.kdca.go.kr/notice"}])

    def test_parses_general_web_task_response(self) -> None:
        result = parse_general_web_task_response(
            '{"title":"보조 맥락","content":"본문","sources":[{"title":"Source","url":"https://example.com"}]}',
            {"checkedAt": "2026-09-04"},
            model="openai/gpt-5.6-sol",
        )

        self.assertEqual(result["title"], "보조 맥락")
        self.assertEqual(result["checkedAt"], "2026-09-04")
        self.assertEqual(result["sources"], [{"title": "Source", "url": "https://example.com"}])

    def test_official_web_summary_prompt_requests_chart_note_guidance_for_benefits(self) -> None:
        self.assertIn("차트 기재 추천", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)
        self.assertIn("급여기준", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)
        self.assertIn("Do not invent patient facts", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)

    def test_official_web_prompts_support_treatment_options(self) -> None:
        self.assertIn("treatment_options", KAOSAI_OFFICIAL_WEB_PLAN_SYSTEM_PROMPT)
        self.assertIn("treatment options/guidelines", KAOSAI_OFFICIAL_WEB_PLAN_SYSTEM_PROMPT)
        self.assertIn("For `treatment_options` tasks", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)
        self.assertIn("abstract-supported clinical points", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)
        self.assertIn("not a personal diagnosis or treatment order", KAOSAI_OFFICIAL_WEB_SUMMARY_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
