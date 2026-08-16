import unittest

from kaos_brain.governor_tools import (
    memo_option_label,
    render_event_create_completed,
    render_event_create_proposal,
    render_memo_create_completed,
    render_memo_delete_completed,
    render_memo_deleted,
    render_memo_edit_completed,
    memo_option_description,
    memo_public_url,
    render_memo_opened,
    render_task_action_completed,
    render_task_create_completed,
    render_task_edit_completed,
    render_task_edit_proposal,
    render_task_due_update_completed,
    render_task_due_update_proposal,
    render_tool_context,
    TaskEditRequest,
)
from kaos_brain.event_intent import EventCreateRequest
from kaos_brain.task_update_intent import TaskActionRequest, TaskCreateRequest, TaskDueUpdateRequest
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
        self.assertEqual(context, "## 할 일\n- none")

    def test_render_supplies_context_uses_scope_title_and_omits_empty_due(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            {"profile": "supplies", "tasks": [{"title": "Soap"}]},
        )
        self.assertEqual(context, "## 비품\n- Soap")

    def test_render_completed_tasks_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.COMPLETED_TASKS, start="2026-08-02", end="2026-08-15"),
            {
                "from": "2026-08-02",
                "to": "2026-08-15",
                "tasks": [{"title": "Call mom", "completedDate": "2026-08-15"}],
            },
        )
        self.assertIn("## 완료한 할 일: 2026-08-02 to 2026-08-15", context)
        self.assertIn("- Call mom - 2026-08-15", context)

    def test_render_family_tasks_context_uses_scope_title(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"profile": "family", "tasks": [{"title": "Call mom", "due": "2026-08-17", "dueTime": "10:00"}]},
        )
        self.assertEqual(context, "## 가족 할 일\n- Call mom - 2026-08-17 10:00")

    def test_render_single_full_memo_context(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.MEMO_SEARCH, "rustdesk"),
            {
                "query": "rustdesk",
                "count": 1,
                "results": [{"name": "memos/42", "content": "# Rustdesk\nUse Tailscale.", "full": True}],
            },
        )
        self.assertIn("Searched..\n## rustdesk\n1 results in 1 memos", context)
        self.assertIn("### Rustdesk\n# Rustdesk\nUse Tailscale.", context)

    def test_render_multiple_memos_context_uses_compact_summary(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.MEMO_SEARCH, "training"),
            {
                "query": "training",
                "resultCount": 2,
                "totalCount": 213,
                "results": [
                    {"name": "memos/1", "snippet": "# Online training\nID and password details " * 20},
                    {"name": "memos/2", "snippet": "Long mandatory training list " * 20},
                ],
            },
        )
        self.assertIn("Searched..\n## training\n2 results in 213 memos", context)
        self.assertNotIn("### Online training", context)
        self.assertNotIn("Memos search:", context)

    def test_memo_option_description_stays_within_discord_limit(self) -> None:
        description = memo_option_description({"snippet": "x" * 200})
        self.assertLessEqual(len(description), 100)

    def test_memo_dropdown_uses_title_and_tags(self) -> None:
        item = {
            "name": "memos/abc",
            "snippet": "# Training note\nsecret body",
            "tags": ["education", "work"],
        }
        self.assertEqual(memo_option_label(item), "Training note")
        self.assertEqual(memo_option_description(item), "#education, #work")

    def test_render_opened_memo_uses_original_markdown(self) -> None:
        content = render_memo_opened(
            "training",
            {
                "name": "memos/abc",
                "content": "# Training note\n\n## Person\n\n- GSEEK\n  - user@example.com\n  - password",
                "tags": ["education"],
            },
        )
        self.assertEqual(
            content,
            "# Training note\n\n## Person\n\n- GSEEK\n  - user@example.com\n  - password",
        )

    def test_render_deleted_memo_keeps_original_content(self) -> None:
        content = render_memo_deleted("# Training note\n\nBody", "2026-08-15 16:30 KST")
        self.assertEqual(content, "# Training note\n\nBody\n\nDeleted at 2026-08-15 16:30 KST")

    def test_memo_public_url_uses_memo_id(self) -> None:
        self.assertEqual(memo_public_url("https://memos.example", "memos/abc"), "https://memos.example/m/abc")
        self.assertEqual(memo_public_url("", "memos/abc"), "")

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
        self.assertIn("Searched..\n## rustdesk\n1 results in 12 documents", context)
        self.assertIn("### Rustdesk setup\n- 2026-08-14 · Clinic · rustdesk.pdf", context)

    def test_render_multiple_documents_context_uses_compact_summary(self) -> None:
        context = render_tool_context(
            ToolRequest(ToolKind.DOCUMENT_SEARCH, "insurance"),
            {
                "query": "insurance",
                "resultCount": 13,
                "totalCount": 213,
                "results": [
                    {
                        "id": 42,
                        "title": "Insurance receipt",
                        "created": "2026-08-14T12:00:00Z",
                        "filename": "receipt.pdf",
                        "correspondent": "Clinic",
                    },
                    {
                        "id": 43,
                        "title": "Insurance form",
                        "created": "2026-08-15T12:00:00Z",
                        "filename": "form.pdf",
                        "correspondent": "Clinic",
                    },
                ],
            },
        )
        self.assertIn("Searched..\n## insurance\n13 results in 213 documents", context)
        self.assertIn("- Showing first 2 results.", context)
        self.assertNotIn("### Insurance receipt", context)
        self.assertNotIn("Document search:", context)

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

    def test_render_task_edit_proposal(self) -> None:
        content = render_task_edit_proposal(
            {
                "task": {
                    "oldTitle": "Call mom",
                    "title": "Call dad",
                    "oldDue": "2026-08-17",
                    "oldDueTime": "10:00",
                    "due": "2026-08-20",
                    "dueTime": "14:30",
                }
            }
        )

        self.assertIn("## Confirm task edit", content)
        self.assertIn("- from: Call mom", content)
        self.assertIn("- to: Call dad", content)
        self.assertIn("- due: 2026-08-17 10:00 -> 2026-08-20 14:30", content)

    def test_render_task_edit_completed(self) -> None:
        self.assertEqual(render_task_edit_completed({"task": {"title": "Call dad"}}), "할 일 수정했어요.")

    def test_render_task_create_completed(self) -> None:
        content = render_task_create_completed(
            {"task": {"title": "Call school", "due": "2026-08-17", "dueTime": "10:00"}}
        )
        self.assertEqual(content, "할 일 저장했어요.")

    def test_render_task_delete_completed(self) -> None:
        content = render_task_action_completed({"task": {"title": "Call school", "action": "delete"}})
        self.assertEqual(content, "할 일 삭제했어요.")

    def test_render_task_reopen_completed(self) -> None:
        content = render_task_action_completed({"task": {"title": "Call school", "action": "reopen"}})
        self.assertEqual(content, "할 일 다시 열었어요.")

    def test_render_event_create_messages(self) -> None:
        proposal = render_event_create_proposal(
            {
                "event": {
                    "title": "엔소쿠료칸",
                    "startDate": "2026-08-15",
                    "allDay": True,
                    "memo": "포항 조사리",
                }
            }
        )
        self.assertIn("## Confirm new event", proposal)
        self.assertIn("- event: 엔소쿠료칸", proposal)
        self.assertIn("- date: 2026-08-15", proposal)
        self.assertIn("- memo: 포항 조사리", proposal)
        self.assertEqual(render_event_create_completed({"event": {"uid": "EVENT-1"}}), "일정 저장했어요.")

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

    async def test_fetch_completed_tasks_builds_filtered_route(self) -> None:
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
        payload = await client.fetch(
            ToolRequest(ToolKind.COMPLETED_TASKS, "엄마", "2026-08-02", "2026-08-15")
        )
        self.assertEqual(payload["path"], "/tools/tasks/completed")
        self.assertEqual(
            payload["params"],
            {
                "profile": "main",
                "limit": "25",
                "query": "엄마",
                "from": "2026-08-02",
                "to": "2026-08-15",
            },
        )

    async def test_fetch_supplies_active_tasks_adds_collection(self) -> None:
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
                supplies_collection_id="supplies:abc",
            )
        )
        payload = await client.fetch(ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"))
        self.assertEqual(payload["path"], "/tools/tasks/active")
        self.assertEqual(payload["params"], {"profile": "supplies", "collectionId": "supplies:abc"})

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

    async def test_event_create_uses_request_profile(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _post(self, path: str, payload: dict[str, object]):
                self.calls.append((path, payload))
                return {"ok": True}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
            )
        )
        await client.propose_event_create(
            EventCreateRequest(
                title="엔소쿠료칸",
                start_date="2026-08-15",
                end_date="2026-08-15",
                memo="포항 조사리",
                profile="family",
            ),
            actor_id=123,
            idempotency_key="k",
        )
        self.assertEqual(client.calls[0][0], "/tools/events/create/proposals")
        self.assertEqual(
            client.calls[0][1],
            {
                "actorId": "123",
                "idempotencyKey": "k",
                "profile": "family",
                "title": "엔소쿠료칸",
                "startDate": "2026-08-15",
                "endDate": "2026-08-15",
                "allDay": True,
                "memo": "포항 조사리",
            },
        )

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

    async def test_task_proposals_use_request_scope(self) -> None:
        from kaos_brain.governor_tools import GovernorToolClient, GovernorToolConfig

        class FakeClient(GovernorToolClient):
            def __init__(self, config: GovernorToolConfig) -> None:
                super().__init__(config)
                self.calls = []

            async def _post(self, path: str, payload: dict[str, str]):
                self.calls.append((path, payload))
                return {"ok": True}

        client = FakeClient(
            GovernorToolConfig(
                base_url="http://127.0.0.1:8098",
                api_token="token",
                profile="main",
                timeout_seconds=1,
                supplies_collection_id="supplies:abc",
            )
        )
        await client.propose_task_create(
            TaskCreateRequest("Soap", "", "", profile="supplies"),
            actor_id=994,
            idempotency_key="discord:1",
        )
        await client.propose_task_action(
            TaskActionRequest("Soap", "reopen", profile="supplies"),
            actor_id=994,
            idempotency_key="discord:2",
        )
        await client.propose_task_edit(
            TaskEditRequest("Soap", "Hand soap", profile="supplies", uid="SUPPLY-1"),
            actor_id=994,
            idempotency_key="discord:3",
        )
        self.assertEqual(client.calls[0][1]["profile"], "supplies")
        self.assertEqual(client.calls[0][1]["collectionId"], "supplies:abc")
        self.assertNotIn("dueDate", client.calls[0][1])
        self.assertNotIn("dueTime", client.calls[0][1])
        self.assertEqual(client.calls[1][1]["profile"], "supplies")
        self.assertEqual(client.calls[1][1]["collectionId"], "supplies:abc")
        self.assertEqual(client.calls[2][0], "/tools/tasks/edit/proposals")
        self.assertEqual(client.calls[2][1]["profile"], "supplies")
        self.assertEqual(client.calls[2][1]["collectionId"], "supplies:abc")
        self.assertEqual(client.calls[2][1]["uid"], "SUPPLY-1")


if __name__ == "__main__":
    unittest.main()
