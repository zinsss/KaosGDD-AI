import unittest
from typing import Any
from importlib.util import find_spec

from kaos_brain.kaos_ai import (
    DisabledKaosAIPlanner,
    KAOSAI_DOCUMENT_TAG_SYSTEM_PROMPT,
    KAOSAI_PLAN_SYSTEM_PROMPT,
    KaosAIConfig,
    KaosAIError,
    OpenClawKaosAIPlanner,
    document_tag_rule_suggestions,
    merge_document_tag_suggestions,
    normalize_kaosai_plan_scope,
    parse_document_tag_response,
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
        self.assertIn("memo.search: query", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("document.update_tags", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("document.update_tags: documentId, tags", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn("task.edit: dueDate, dueTime, memo, priority, taskTitle, title", KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn('Default scope to "personal"', KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertIn('Use "family" only for explicitly shared family', KAOSAI_PLAN_SYSTEM_PROMPT)
        self.assertNotIn("collectionId", KAOSAI_PLAN_SYSTEM_PROMPT)

    def test_document_tag_prompt_limits_ai_to_existing_tags(self) -> None:
        self.assertIn("Prefer tag names from availableTags", KAOSAI_DOCUMENT_TAG_SYSTEM_PROMPT)
        self.assertIn("user to confirm before creating", KAOSAI_DOCUMENT_TAG_SYSTEM_PROMPT)

    def test_parse_document_tag_response_keeps_existing_tags_only(self) -> None:
        tags = parse_document_tag_response(
            '{"tags":["clinic","made-up","Receipt","clinic"]}',
            {"availableTags": [{"id": 1, "name": "Clinic"}, {"id": 2, "name": "receipt"}]},
        )

        self.assertEqual(tags, ("Clinic", "made-up", "receipt"))

    def test_document_tag_rules_detect_certificate_name_and_year_tags(self) -> None:
        tags = document_tag_rule_suggestions(
            {
                "document": {
                    "title": "2023 진단용방사선안전관리책임자교육-이수증",
                    "filename": "2023 진단용방사선안전관리책임자교육-이수증.pdf",
                    "contentExcerpt": "성 명 홍길동\n교육 이수 완료",
                },
                "availableTags": [
                    {"id": 1, "name": "이수증"},
                    {"id": 2, "name": "수료증"},
                    {"id": 3, "name": "홍길동"},
                    {"id": 4, "name": "2023"},
                    {"id": 5, "name": "의료"},
                ],
            }
        )

        self.assertEqual(tags, ("이수증", "홍길동", "2023"))

    def test_document_tag_rules_detect_completion_certificate_tag(self) -> None:
        tags = document_tag_rule_suggestions(
            {
                "document": {"title": "감염관리 교육 수료증", "contentExcerpt": "이름 김영희"},
                "availableTags": [
                    {"id": 1, "name": "#수료증"},
                    {"id": 2, "name": "김영희"},
                ],
            }
        )

        self.assertEqual(tags, ("#수료증", "김영희"))

    def test_document_tag_rules_never_invent_missing_tags_and_merge_before_ai(self) -> None:
        context = {
            "document": {"title": "2024 교육 이수증", "contentExcerpt": "성명 없는사람"},
            "availableTags": [{"id": 1, "name": "이수증"}],
        }

        self.assertEqual(document_tag_rule_suggestions(context), ("이수증", "없는사람", "2024"))
        self.assertEqual(merge_document_tag_suggestions(("이수증",), ("Clinic", "이수증")), ("이수증", "Clinic"))

    async def test_disabled_planner_returns_no_document_tags(self) -> None:
        planner = DisabledKaosAIPlanner()

        self.assertEqual(await planner.suggest_document_tags({}), ())

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

    def test_scope_normalization_demotes_implicit_family_to_personal(self) -> None:
        plan = {
            "intent": "task.create",
            "scope": "family",
            "parameters": {"title": "엄마한테 전화", "dueDate": "2026-08-20"},
        }

        normalized = normalize_kaosai_plan_scope("내일까지 엄마한테 전화해야돼", plan)
        family = normalize_kaosai_plan_scope("가족 할 일로 로운이 준비물 챙기기", plan)

        self.assertEqual(normalized["scope"], "personal")
        self.assertEqual(family["scope"], "family")

    def test_rejects_invalid_or_non_object_json(self) -> None:
        with self.assertRaisesRegex(KaosAIError, "invalid_kaosai_json"):
            parse_kaosai_plan_response("not json")
        with self.assertRaisesRegex(KaosAIError, "kaosai_plan_must_be_object"):
            parse_kaosai_plan_response("[]")
        with self.assertRaisesRegex(KaosAIError, "kaosai_parameters_required"):
            parse_kaosai_plan_response('{"intent":"memo.search","parameters":[]}')

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OpenClawKaosAIPlanner tests")
    async def test_openclaw_planner_uses_gateway_contract(self) -> None:
        requests: list[dict[str, Any]] = []

        async def handler(request):
            websocket = web.WebSocketResponse()
            await websocket.prepare(request)
            await websocket.send_json({"type": "event", "event": "connect.challenge", "payload": {"nonce": "nonce"}})
            async for message in websocket:
                frame = message.json()
                requests.append(frame)
                if frame["method"] == "connect":
                    await websocket.send_json({"type": "res", "id": frame["id"], "ok": True, "payload": {"features": {"methods": ["agent"]}}})
                elif frame["method"] == "agent":
                    await websocket.send_json({"type": "res", "id": frame["id"], "ok": True, "payload": {"status": "accepted"}})
                    await websocket.send_json(
                        {
                            "type": "res",
                            "id": frame["id"],
                            "ok": True,
                            "payload": {
                                "status": "ok",
                                "result": {
                                    "payloads": [
                                        {
                                            "text": '{"intent":"memo.search","scope":"personal","parameters":{"query":"rustdesk"}}'
                                        }
                                    ]
                                },
                            },
                        }
                    )
            return websocket

        runner, base_url = await self._start_server(handler)
        try:
            planner = OpenClawKaosAIPlanner(
                KaosAIConfig(
                    enabled=True,
                    provider="openclaw",
                    base_url=base_url,
                    model="ollama/gemma4",
                    api_token="gateway-token",
                    timeout_seconds=1,
                )
            )

            plan = await planner.plan("rustdesk 메모 찾아줘", context={"actorId": "1", "channelId": "2", "today": "2026-08-17"})

            self.assertEqual(plan["intent"], "memo.search")
            self.assertEqual(plan["parameters"]["query"], "rustdesk")
            self.assertEqual(requests[0]["method"], "connect")
            self.assertEqual(requests[0]["params"]["auth"]["token"], "gateway-token")
            self.assertEqual(requests[0]["params"]["client"]["id"], "gateway-client")
            self.assertEqual(requests[1]["method"], "agent")
            self.assertEqual(requests[1]["params"]["provider"], "ollama")
            self.assertEqual(requests[1]["params"]["model"], "gemma4")
            self.assertTrue(requests[1]["params"]["modelRun"])
            self.assertEqual(requests[1]["params"]["promptMode"], "none")
            self.assertIn("cannot call tools", requests[1]["params"]["message"])
            self.assertIn("rustdesk 메모 찾아줘", requests[1]["params"]["message"])
        finally:
            await runner.cleanup()

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OpenClawKaosAIPlanner tests")
    async def test_openclaw_planner_rejects_gateway_error_or_bad_json(self) -> None:
        async def gateway_error(request):
            websocket = web.WebSocketResponse()
            await websocket.prepare(request)
            await websocket.send_json({"type": "event", "event": "connect.challenge", "payload": {"nonce": "nonce"}})
            async for message in websocket:
                frame = message.json()
                await websocket.send_json(
                    {
                        "type": "res",
                        "id": frame["id"],
                        "ok": False,
                        "error": {"code": "UNAVAILABLE", "message": "down"},
                    }
                )
            return websocket

        runner, base_url = await self._start_server(gateway_error)
        try:
            planner = OpenClawKaosAIPlanner(
                KaosAIConfig(enabled=True, provider="openclaw", base_url=base_url, api_token="gateway-token", timeout_seconds=1)
            )
            with self.assertRaisesRegex(KaosAIError, "kaosai_gateway_connect_failed"):
                await planner.plan("hello", context={})
        finally:
            await runner.cleanup()

        async def invalid_plan(request):
            websocket = web.WebSocketResponse()
            await websocket.prepare(request)
            await websocket.send_json({"type": "event", "event": "connect.challenge", "payload": {"nonce": "nonce"}})
            async for message in websocket:
                frame = message.json()
                if frame["method"] == "connect":
                    await websocket.send_json({"type": "res", "id": frame["id"], "ok": True, "payload": {}})
                elif frame["method"] == "agent":
                    await websocket.send_json(
                        {
                            "type": "res",
                            "id": frame["id"],
                            "ok": True,
                            "payload": {"status": "ok", "result": {"payloads": [{"text": "not json"}]}},
                        }
                    )
            return websocket

        runner, base_url = await self._start_server(invalid_plan)
        try:
            planner = OpenClawKaosAIPlanner(
                KaosAIConfig(enabled=True, provider="openclaw", base_url=base_url, api_token="gateway-token", timeout_seconds=1)
            )
            with self.assertRaisesRegex(KaosAIError, "invalid_kaosai_json"):
                await planner.plan("hello", context={})
        finally:
            await runner.cleanup()

    @staticmethod
    async def _start_server(handler):
        app = web.Application()
        app.router.add_get("/", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sockets = site._server.sockets
        port = sockets[0].getsockname()[1]
        return runner, f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    unittest.main()
