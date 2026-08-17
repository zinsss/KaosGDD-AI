import unittest
from importlib.util import find_spec

from kaos_brain.kaos_ai import (
    DisabledKaosAIPlanner,
    KAOSAI_PLAN_SYSTEM_PROMPT,
    KaosAIConfig,
    KaosAIError,
    OpenClawKaosAIPlanner,
    parse_kaosai_plan_response,
)

AIOHTTP_AVAILABLE = find_spec("aiohttp") is not None

if AIOHTTP_AVAILABLE:
    from aiohttp import web


class KaosAITests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_planner_returns_no_plan(self) -> None:
        planner = DisabledKaosAIPlanner()

        self.assertIsNone(await planner.plan("hello", context={}))

    def test_plan_prompt_forbids_direct_tool_access(self) -> None:
        self.assertIn("cannot call tools", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("Do not produce shell", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("task.update_due", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("memo.search", KAOSAI_PLAN_SYSTEM_PROMPT)

    def test_parse_strict_plan_json(self) -> None:
        plan = parse_kaosai_plan_response(
            '{"intent":"memo.search","scope":"personal","parameters":{"query":"rustdesk"}}'
        )

        self.assertEqual(plan["intent"], "memo.search")
        self.assertEqual(plan["parameters"]["query"], "rustdesk")

    def test_parse_json_fence_from_provider(self) -> None:
        plan = parse_kaosai_plan_response(
            '```json\n{"intent":"today.get","scope":"personal","parameters":{}}\n```'
        )

        self.assertEqual(plan["intent"], "today.get")

    def test_clarify_plan_requires_question(self) -> None:
        plan = parse_kaosai_plan_response(
            '{"intent":"clarify","scope":"personal","parameters":{"question":"어떤 메모인가요?"}}'
        )

        self.assertEqual(plan["intent"], "clarify")
        with self.assertRaisesRegex(KaosAIError, "kaosai_clarify_question_required"):
            parse_kaosai_plan_response('{"intent":"clarify","scope":"personal","parameters":{}}')

    def test_rejects_invalid_or_non_object_json(self) -> None:
        with self.assertRaisesRegex(KaosAIError, "invalid_kaosai_json"):
            parse_kaosai_plan_response("not json")
        with self.assertRaisesRegex(KaosAIError, "kaosai_plan_must_be_object"):
            parse_kaosai_plan_response("[]")
        with self.assertRaisesRegex(KaosAIError, "kaosai_parameters_required"):
            parse_kaosai_plan_response('{"intent":"memo.search","parameters":[]}')

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OpenClawKaosAIPlanner tests")
    async def test_openclaw_planner_uses_chat_completions_contract(self) -> None:
        requests = []

        async def handler(request):
            requests.append({"headers": request.headers, "json": await request.json()})
            return web.json_response(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"intent":"memo.search","scope":"personal","parameters":{"query":"rustdesk"}}'
                            }
                        }
                    ]
                }
            )

        runner, base_url = await self._start_server(handler)
        try:
            planner = OpenClawKaosAIPlanner(
                KaosAIConfig(
                    enabled=True,
                    provider="openclaw",
                    base_url=base_url,
                    model="gpt-5-thinking",
                    api_token="gateway-token",
                    timeout_seconds=1,
                )
            )

            plan = await planner.plan("rustdesk 메모 찾아줘", context={"actorId": "1", "channelId": "2", "today": "2026-08-17"})

            self.assertEqual(plan["intent"], "memo.search")
            self.assertEqual(plan["parameters"]["query"], "rustdesk")
            self.assertEqual(requests[0]["headers"]["Authorization"], "Bearer gateway-token")
            self.assertEqual(requests[0]["json"]["model"], "gpt-5-thinking")
            self.assertEqual(requests[0]["json"]["stream"], False)
            self.assertEqual(requests[0]["json"]["temperature"], 0)
            self.assertIn("cannot call tools", requests[0]["json"]["messages"][0]["content"])
            self.assertIn("rustdesk 메모 찾아줘", requests[0]["json"]["messages"][1]["content"])
        finally:
            await runner.cleanup()

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OpenClawKaosAIPlanner tests")
    async def test_openclaw_planner_rejects_bad_http_or_bad_json(self) -> None:
        async def http_error(_request):
            return web.Response(status=503, text="down")

        runner, base_url = await self._start_server(http_error)
        try:
            planner = OpenClawKaosAIPlanner(KaosAIConfig(enabled=True, provider="openclaw", base_url=base_url, timeout_seconds=1))
            with self.assertRaisesRegex(KaosAIError, "kaosai_http_503"):
                await planner.plan("hello", context={})
        finally:
            await runner.cleanup()

        async def invalid_plan(_request):
            return web.json_response({"choices": [{"message": {"content": "not json"}}]})

        runner, base_url = await self._start_server(invalid_plan)
        try:
            planner = OpenClawKaosAIPlanner(KaosAIConfig(enabled=True, provider="openclaw", base_url=base_url, timeout_seconds=1))
            with self.assertRaisesRegex(KaosAIError, "invalid_kaosai_json"):
                await planner.plan("hello", context={})
        finally:
            await runner.cleanup()

    @staticmethod
    async def _start_server(handler):
        app = web.Application()
        app.router.add_post("/v1/chat/completions", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sockets = site._server.sockets
        port = sockets[0].getsockname()[1]
        return runner, f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    unittest.main()
