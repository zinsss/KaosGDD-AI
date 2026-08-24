from types import SimpleNamespace
import unittest

from kaos_brain.bot import BrainBot, BrainCombinedSearchView
from kaos_brain.governor_tools import GovernorToolError
from kaos_brain.tool_intent import ToolKind, ToolRequest


class FailingGovernorTools:
    async def fetch(self, request: ToolRequest):
        raise GovernorToolError("upstream exploded with details")


class MemoGovernorTools:
    async def fetch(self, request: ToolRequest):
        return {
            "query": request.query,
            "resultCount": 1,
            "totalCount": 1,
            "results": [{"name": "memos/42", "content": "# Rustdesk\nUse Tailscale.", "full": True}],
        }


class DocumentGovernorTools:
    async def fetch(self, request: ToolRequest):
        return {
            "query": request.query,
            "resultCount": 1,
            "totalCount": 1,
            "results": [
                {
                    "id": 42,
                    "title": "Insurance receipt",
                    "created": "2026-08-14T12:00:00Z",
                    "filename": "receipt.pdf",
                    "correspondent": "Clinic",
                    "url": "https://paperless.example/documents/42/details",
                    "full": True,
                }
            ],
        }


class CombinedGovernorTools:
    async def fetch(self, request: ToolRequest):
        if request.kind is ToolKind.MEMO_SEARCH:
            return {
                "query": request.query,
                "resultCount": 30,
                "totalCount": 30,
                "results": [{"name": f"memos/{index}", "content": f"# Rustdesk {index}", "full": True} for index in range(25)],
            }
        if request.kind is ToolKind.DOCUMENT_SEARCH:
            return {
                "query": request.query,
                "resultCount": 30,
                "totalCount": 30,
                "results": [{"id": index + 1, "title": f"Rustdesk setup {index + 1}"} for index in range(25)],
            }
        raise AssertionError(f"unexpected request: {request.kind}")


class CombinedMemoOnlyGovernorTools:
    async def fetch(self, request: ToolRequest):
        if request.kind is ToolKind.MEMO_SEARCH:
            return {
                "query": request.query,
                "resultCount": 1,
                "totalCount": 6,
                "results": [{"name": "memos/42", "content": "# 통관", "full": True}],
            }
        if request.kind is ToolKind.DOCUMENT_SEARCH:
            return {
                "query": request.query,
                "resultCount": 0,
                "totalCount": 26,
                "results": [],
            }
        raise AssertionError(f"unexpected request: {request.kind}")


class WeatherGovernorTools:
    async def fetch(self, request: ToolRequest):
        self.request = request
        return {
            "date": "2026-08-14",
            "weather": {
                "summary": "⛅️ 23-28℃",
                "condition": "cloudy",
                "precipitationProbability": 70,
                "humidityPercent": 81,
                "windSpeedKmh": 13.2,
            },
        }


class BrainToolResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_governor_tools_uses_short_korean_message(self) -> None:
        brain = SimpleNamespace(governor_tools=None)

        reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
            brain,
            "오늘 뭐 있어?",
            ToolRequest(ToolKind.TODAY),
            actor_id=200,
        )

        self.assertEqual(reply, "Governor 연결이 아직 없어요.")
        self.assertIsNone(view)

    async def test_governor_tool_failure_hides_internal_error_details(self) -> None:
        brain = SimpleNamespace(governor_tools=FailingGovernorTools())

        with self.assertLogs("kaos_brain.bot", level="WARNING"):
            reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
                brain,
                "오늘 뭐 있어?",
                ToolRequest(ToolKind.TODAY),
                actor_id=200,
            )

        self.assertEqual(reply, "조회 실패했어요.")
        self.assertNotIn("upstream exploded", reply)
        self.assertIsNone(view)

    async def test_weather_request_returns_deterministic_weather_without_kaosai_summary(self) -> None:
        tools = WeatherGovernorTools()
        brain = SimpleNamespace(governor_tools=tools)

        reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
            brain,
            "지금 포항날씨는?",
            ToolRequest(ToolKind.WEATHER, "포항"),
            actor_id=200,
        )

        self.assertEqual(reply, "## 포항 날씨\n- ⛅️ 23-28℃\n- 강수확률 70% · 습도 81% · 바람 13.2km/h\n- 2026-08-14")
        self.assertIsNone(view)

    async def test_single_memo_search_opens_original_memo_with_actions(self) -> None:
        brain = SimpleNamespace(governor_tools=MemoGovernorTools())

        reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
            brain,
            "rustdesk 메모 찾아줘",
            ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"),
            actor_id=200,
        )

        self.assertEqual(reply, "# Rustdesk\nUse Tailscale.")
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual([item.label for item in view.children], ["Close", "More..."])

    async def test_single_document_search_returns_link_list_window(self) -> None:
        brain = SimpleNamespace(
            governor_tools=DocumentGovernorTools(),
            settings=SimpleNamespace(paperless_public_url="https://paperless.example"),
        )

        reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
            brain,
            "보험 문서 찾아줘",
            ToolRequest(ToolKind.DOCUMENT_SEARCH, "보험"),
            actor_id=200,
        )

        self.assertEqual(
            reply,
            "Searched..\n"
            "## 보험\n"
            "1 results in 1 documents\n"
            "Page 1 / 1\n"
            "- Insurance receipt · [open](https://paperless.example/documents/42/details)",
        )
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual([item.label for item in view.children], [])

    async def test_combined_search_returns_memos_and_documents(self) -> None:
        brain = SimpleNamespace(
            governor_tools=CombinedGovernorTools(),
            settings=SimpleNamespace(
                paperless_public_url="https://paperless.example",
                memos_public_url="https://memos.example",
            ),
        )

        reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
            brain,
            "..rustdesk",
            ToolRequest(ToolKind.SEARCH_ALL, "rustdesk"),
            actor_id=200,
        )

        self.assertIn("Searched..\n## rustdesk", reply)
        self.assertIn("- Memos: 30 results in 30 memos", reply)
        self.assertIn("- Paperless: 30 results in 30 documents", reply)
        self.assertIn("- Memos: more than 20 found. First 20 shown.", reply)
        self.assertIn("- Paperless: more than 20 found. First 20 shown.", reply)
        self.assertNotIn("Rustdesk setup 1 · [open]", reply)
        self.assertIsNotNone(view)
        self.assertIsInstance(view, BrainCombinedSearchView)
        assert isinstance(view, BrainCombinedSearchView)
        self.assertEqual(
            [getattr(item, "placeholder", "") for item in view.children if getattr(item, "placeholder", "")],
            ["Memos: 30", "Paperless: 30"],
        )
        self.assertEqual(
            [getattr(item, "label", "") for item in view.children if getattr(item, "label", "")],
            ["Paperless", "Memos"],
        )

    async def test_combined_search_omits_redundant_no_match_lines(self) -> None:
        brain = SimpleNamespace(
            governor_tools=CombinedMemoOnlyGovernorTools(),
            settings=SimpleNamespace(
                paperless_public_url="https://paperless.example",
                memos_public_url="https://memos.example",
            ),
        )

        reply, view = await BrainBot._answer_with_governor_tool(  # type: ignore[arg-type]
            brain,
            "..통관",
            ToolRequest(ToolKind.SEARCH_ALL, "통관"),
            actor_id=200,
        )

        self.assertEqual(
            reply,
            "Searched..\n"
            "## 통관\n"
            "- Memos: 1 results in 6 memos\n"
            "- Paperless: 0 results in 26 documents",
        )
        self.assertIsNotNone(view)
        self.assertIsInstance(view, BrainCombinedSearchView)


if __name__ == "__main__":
    unittest.main()
