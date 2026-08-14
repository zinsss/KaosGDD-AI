import unittest

from kaos_brain.tool_intent import ToolKind, parse_tool_request


class ToolIntentTests(unittest.TestCase):
    def test_today_korean_request(self) -> None:
        request = parse_tool_request("오늘 뭐 있어?")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.TODAY)

    def test_active_task_korean_request(self) -> None:
        request = parse_tool_request("뭐 해야 돼?")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.ACTIVE_TASKS)

    def test_memo_search_extracts_query(self) -> None:
        request = parse_tool_request("메모에서 rust desk 찾아줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.MEMO_SEARCH)
        self.assertEqual(request.query, "rust desk")

    def test_document_search_extracts_query(self) -> None:
        request = parse_tool_request("문서에서 보험 찾아줘")
        assert request is not None
        self.assertEqual(request.kind, ToolKind.DOCUMENT_SEARCH)
        self.assertEqual(request.query, "보험")

    def test_plain_chat_does_not_trigger_tool(self) -> None:
        self.assertIsNone(parse_tool_request("안녕"))


if __name__ == "__main__":
    unittest.main()
