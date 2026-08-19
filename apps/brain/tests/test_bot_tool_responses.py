from types import SimpleNamespace
import unittest

from kaos_brain.bot import BrainBot
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

    async def test_single_document_search_opens_document_with_close(self) -> None:
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
            "## Insurance receipt\n- 2026-08-14 · Clinic · receipt.pdf\nhttps://paperless.example/documents/42/details",
        )
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual([item.label for item in view.children], ["Close", "Open document"])


if __name__ == "__main__":
    unittest.main()
