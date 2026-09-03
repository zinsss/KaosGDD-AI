from __future__ import annotations

import unittest
from importlib.util import find_spec

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


if __name__ == "__main__":
    unittest.main()
