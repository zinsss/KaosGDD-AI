import unittest
from importlib.util import find_spec

from kaos_brain.intent import Route
from kaos_brain.router import RouteDecision, parse_route_decision


AIOHTTP_AVAILABLE = find_spec("aiohttp") is not None


if AIOHTTP_AVAILABLE:
    from kaos_brain.ollama import OllamaClient, OllamaConfig, OllamaError
else:
    OllamaClient = object  # type: ignore[assignment,misc]
    OllamaConfig = None  # type: ignore[assignment]
    OllamaError = RuntimeError  # type: ignore[assignment]


class FakeOllamaClient(OllamaClient):  # type: ignore[misc,valid-type]
    def __init__(self, responses: list[str | Exception]) -> None:
        super().__init__(
            OllamaConfig(
                base_url="http://127.0.0.1:11434",
                chat_model="gemma3:4b",
                deep_model="qwen3:8b",
                timeout_seconds=1,
            )
        )
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    async def _complete(self, model: str, messages: list[dict[str, str]], *, num_predict: int) -> str:
        self.calls.append((model, num_predict))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class OllamaRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_route_decision_accepts_deep_prefix_and_falls_back_to_answer(self) -> None:
        self.assertEqual(parse_route_decision("deep\n"), RouteDecision.DEEP)
        self.assertEqual(parse_route_decision('{"route": "deep"}'), RouteDecision.ANSWER)
        self.assertEqual(parse_route_decision("anything else"), RouteDecision.ANSWER)

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OllamaClient tests")
    async def test_generate_auto_uses_chat_model_when_router_says_answer(self) -> None:
        client = FakeOllamaClient(["answer", "안녕"])
        reply = await client.generate_auto("안녕")
        self.assertEqual(reply, "안녕")
        self.assertEqual(client.calls, [("gemma3:4b", 8), ("gemma3:4b", 512)])

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OllamaClient tests")
    async def test_generate_auto_uses_deep_model_when_router_says_deep(self) -> None:
        client = FakeOllamaClient(["deep", "정리된 답"])
        reply = await client.generate_auto("migration plan risk 분석")
        self.assertEqual(reply, "정리된 답")
        self.assertEqual(client.calls, [("gemma3:4b", 8), ("qwen3:8b", 512)])

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OllamaClient tests")
    async def test_router_failure_falls_back_to_chat_model(self) -> None:
        client = FakeOllamaClient([OllamaError("boom"), "fallback"])
        reply = await client.generate_auto("안녕")
        self.assertEqual(reply, "fallback")
        self.assertEqual(client.calls, [("gemma3:4b", 8), ("gemma3:4b", 512)])

    @unittest.skipUnless(AIOHTTP_AVAILABLE, "aiohttp is required for OllamaClient tests")
    async def test_manual_deep_generation_skips_router(self) -> None:
        client = FakeOllamaClient(["deep answer"])
        reply = await client.generate(Route.DEEP, "생각해줘")
        self.assertEqual(reply, "deep answer")
        self.assertEqual(client.calls, [("qwen3:8b", 512)])


if __name__ == "__main__":
    unittest.main()
