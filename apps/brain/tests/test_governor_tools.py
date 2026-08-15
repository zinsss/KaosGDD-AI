import unittest

from kaos_brain.governor_tools import (
    render_memo_create_completed,
    render_memo_delete_completed,
    render_memo_edit_completed,
    render_task_action_completed,
    render_task_create_completed,
    render_task_due_update_completed,
    render_task_due_update_proposal,
    render_tool_context,
)
from kaos_brain.task_update_intent import TaskDueUpdateRequest
from kaos_brain.tool_intent import ToolKind, ToolRequest


class GovernorToolRenderingTests(unittest.TestCase):
    def test_render_today_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.TODAY),
            {
                "date": "2026-08-14",
                "weather": {"summary": "⛅️ 23-28℃"},
                "events": [{"title": "Clinic", "time": "10:00", "ownerLabel": "GDD_ZiN"}],
                "tasks": [{"title": "Call mom", "due": "2026-08-14", "dueTime": "10:00"}],
            },
        )
        self.assertIn("Today: 2026-08-14", context)
        self.assertIn("Weather: ⛅️ 23-28℃", context)
        self.assertIn("- 10:00 Clinic (GDD_ZiN)", context)
        self.assertIn("- Call mom - 2026-08-14 10:00", context)

    def test_render_empty_tasks_context(self) -> None:
        context = render_tool_context(ToolRequest(ToolKind.ACTIVE_TASKS), {"tasks": []})
        self.assertEqual(context, "Active tasks: none")

    def test_render_single_full_memo_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"),
            {
                "query": "rustdesk",
                "count": 1,
                "results": [{"name": "memos/42", "content": "# Rustdesk\nUse Tailscale.", "full": True}],
            },
        )
        self.assertIn("Memos search: rustdesk (1 results)", context)
        self.assertIn("# Rustdesk\nUse Tailscale.", context)

    def test_render_single_full_document_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.DOCUMENT_SEARCH, "rustdesk"),
            {
                "query": "rustdesk",
                "resultCount": 1,
                "totalCount": 12,
                "results": [
                    {
                        "id": 42,
                        "title": "Rustdesk setup",
                        "created": "2026-08-14T12:00:00Z",
                        "filename": "rustdesk.pdf",
                        "correspondent": "Clinic",
                        "full": True,
                    }
                ],
            },
        )
        self.assertIn("Document search: rustdesk (12 results)", context)
        self.assertIn("- Rustdesk setup - 2026-08-14 / Clinic / rustdesk.pdf", context)

    def test_render_task_due_update_proposal(self) -> None:
        content = render_task_due_update_proposal(
            {"task": {"title": "Call mom", "oldDue": "2026-08-14", "oldDueTime": "10:00", "newDue": "2026-08-17", "newDueTime": "10:00"}}
        )
        self.assertIn("## Confirm task edit", content)
        self.assertIn("- task: Call mom", content)
        self.assertIn("- to: 2026-08-17 10:00", content)

    def test_render_task_due_update_completed(self) -> None:
        content = render_task_due_update_completed(
            {"task": {"title": "Call mom", "newDue": "2026-08-17", "newDueTime": "10:00"}}
        )
        self.assertEqual(content, "할 일 수정했어요.")

    def test_render_task_create_completed(self) -> None:
        content = render_task_create_completed(
            {"task": {"title": "Call school", "due": "2026-08-17", "dueTime": "10:00"}}
        )
        self.assertEqual(content, "할 일 저장했어요.")

    def test_render_task_delete_completed(self) -> None:
        content = render_task_action_completed({"task": {"title": "Call school", "action": "delete"}})
        self.assertEqual(content, "할 일 삭제했어요.")

    def test_render_memo_completion_messages(self) -> None:
        self.assertEqual(
            render_memo_create_completed({"memo": {"name": "memos/42"}}),
            "메모 저장했어요.",
        )
        self.assertEqual(
            render_memo_delete_completed({"memo": {"name": "memos/42"}}),
            "메모 삭제했어요.",
        )
        self.assertEqual(
            render_memo_edit_completed({"memo": {"name": "memos/42"}}),
            "메모 수정했어요.",
        )


class GovernorToolClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_builds_today_route(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _get(self, path: str, params: dict[str, str]):
                return {"path": path, "params": params}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.TODAY))
        self.assertEqual(payload["path"], "/tools/today")
        self.assertEqual(payload["params"], {"profile": "main"})

    async def test_fetch_single_memo_search_gets_full_body(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                if path == "/tools/memos/search":
                    return {"query": "rustdesk", "count": 1, "results": [{"name": "memos/42", "snippet": "Rustdesk"}]}
                return {"memo": {"name": "memos/42", "content": "# Rustdesk\nUse Tailscale."}}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"))
        self.assertEqual(
            client.calls,
            [
                ("/tools/memos/search", {"query": "rustdesk", "limit": "5"}),
                ("/tools/memos/42", {}),
            ],
        )
        self.assertEqual(payload["results"][0]["content"], "# Rustdesk\nUse Tailscale.")
        self.assertTrue(payload["results"][0]["full"])

    async def test_fetch_multi_memo_search_keeps_snippets_only(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {
                    "query": "rustdesk",
                    "count": 2,
                    "results": [{"name": "memos/42", "snippet": "One"}, {"name": "memos/43", "snippet": "Two"}],
                }

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"))
        self.assertEqual(client.calls, [("/tools/memos/search", {"query": "rustdesk", "limit": "5"})])
        self.assertNotIn("content", payload["results"][0])

    async def test_fetch_single_document_search_gets_detail(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                if path == "/tools/documents/search":
                    return {"query": "rustdesk", "resultCount": 1, "totalCount": 12, "results": [{"id": 42, "title": "Rustdesk"}]}
                return {"document": {"id": 42, "title": "Rustdesk setup", "filename": "rustdesk.pdf", "correspondent": "Clinic"}}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.DOCUMENT_SEARCH, "rustdesk"))
        self.assertEqual(
            client.calls,
            [
                ("/tools/documents/search", {"query": "rustdesk", "limit": "5"}),
                ("/tools/documents/42", {}),
            ],
        )
        self.assertEqual(payload["results"][0]["title"], "Rustdesk setup")
        self.assertTrue(payload["results"][0]["full"])

    async def test_fetch_multi_document_search_keeps_search_rows(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _get(self, path: str, params: dict[str, str]):
                self.calls.append((path, params))
                return {"query": "rustdesk", "resultCount": 2, "results": [{"id": 42, "title": "One"}, {"id": 43, "title": "Two"}]}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.DOCUMENT_SEARCH, "rustdesk"))
        self.assertEqual(client.calls, [("/tools/documents/search", {"query": "rustdesk", "limit": "5"})])
        self.assertNotIn("full", payload["results"][0])

    async def test_propose_task_due_update_posts_contract(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            async def _post(self, path: str, payload: dict[str, str]):
                return {"path": path, "payload": payload}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        payload = await client.propose_task_due_update(
            TaskDueUpdateRequest("Call mom", "2026-08-17"),
            actor_id=994,
            idempotency_key="discord:1",
        )
        self.assertEqual(payload["path"], "/tools/tasks/update-due/proposals")
        self.assertEqual(payload["payload"]["taskTitle"], "Call mom")
        self.assertEqual(payload["payload"]["dueTime"], "10:00")


if __name__ == "__main__":
    unittest.main()
