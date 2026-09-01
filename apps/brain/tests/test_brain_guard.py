import unittest
from datetime import date

from kaos_brain.brain_guard import (
    ALLOWED_INTENTS,
    BrainGuardContext,
    BrainGuardError,
    BrainGuardResultKind,
    INTENT_PARAMETER_KEYS,
    PLAN_TOP_LEVEL_KEYS,
    adapt_kaosai_plan,
)
from kaos_brain.event_intent import EventCreateRequest
from kaos_brain.governor_tools import DocumentTagRequest, TaskEditRequest
from kaos_brain.memo_intent import MemoCreateRequest
from kaos_brain.task_update_intent import TaskActionRequest, TaskCreateRequest, TaskDueUpdateRequest
from kaos_brain.tool_intent import ToolKind, ToolRequest


class BrainGuardTests(unittest.TestCase):
    def context(self) -> BrainGuardContext:
        return BrainGuardContext(
            actor_id=123,
            idempotency_key="discord:message:1",
            today=date(2026, 8, 17),
            supplies_collection_id="supplies:abc",
        )

    def test_plan_contract_matches_allowed_intents(self) -> None:
        self.assertEqual(PLAN_TOP_LEVEL_KEYS, frozenset({"intent", "scope", "parameters"}))
        self.assertEqual(set(INTENT_PARAMETER_KEYS), ALLOWED_INTENTS)
        self.assertEqual(
            INTENT_PARAMETER_KEYS["task.edit"],
            frozenset({"taskTitle", "title", "memo", "dueDate", "dueTime", "priority"}),
        )
        self.assertEqual(INTENT_PARAMETER_KEYS["task.create"], frozenset({"title", "memo", "dueDate", "dueTime"}))
        self.assertEqual(INTENT_PARAMETER_KEYS["today.get"], frozenset({"date", "startDate"}))
        self.assertEqual(INTENT_PARAMETER_KEYS["memo.search"], frozenset({"query"}))
        self.assertEqual(INTENT_PARAMETER_KEYS["document.search"], frozenset({"query"}))
        self.assertEqual(INTENT_PARAMETER_KEYS["system.status"], frozenset())
        self.assertEqual(INTENT_PARAMETER_KEYS["document.update_tags"], frozenset({"documentId", "tags"}))

    def test_memo_search_plan_becomes_readonly_governor_tool(self) -> None:
        result = adapt_kaosai_plan(
            {"intent": "memo.search", "parameters": {"query": "의무교육"}},
            self.context(),
        )

        self.assertEqual(result.kind, BrainGuardResultKind.READONLY_TOOL)
        self.assertFalse(result.confirmation_required)
        self.assertIsInstance(result.request, ToolRequest)
        request = result.request
        assert isinstance(request, ToolRequest)
        self.assertEqual(request.kind, ToolKind.MEMO_SEARCH)
        self.assertEqual(request.query, "의무교육")

    def test_today_plan_preserves_requested_date(self) -> None:
        for key in ("date", "startDate"):
            with self.subTest(key=key):
                result = adapt_kaosai_plan(
                    {"intent": "today.get", "parameters": {key: "2026-08-26"}},
                    self.context(),
                )

                self.assertEqual(result.kind, BrainGuardResultKind.READONLY_TOOL)
                self.assertFalse(result.confirmation_required)
                self.assertIsInstance(result.request, ToolRequest)
                request = result.request
                assert isinstance(request, ToolRequest)
                self.assertEqual(request.kind, ToolKind.TODAY)
                self.assertEqual(request.start, "2026-08-26")

    def test_system_status_plan_becomes_readonly_governor_tool(self) -> None:
        result = adapt_kaosai_plan(
            {"intent": "system.status", "parameters": {}},
            self.context(),
        )

        self.assertEqual(result.kind, BrainGuardResultKind.READONLY_TOOL)
        self.assertFalse(result.confirmation_required)
        self.assertIsInstance(result.request, ToolRequest)
        request = result.request
        assert isinstance(request, ToolRequest)
        self.assertEqual(request.kind, ToolKind.SYSTEM_STATUS)

    def test_task_create_plan_requires_confirmation_and_defaults_due_time(self) -> None:
        result = adapt_kaosai_plan(
            {
                "intent": "task.create",
                "parameters": {"title": "엄마한테 전화", "memo": "병원 끝나고", "dueDate": "2026-08-18"},
            },
            self.context(),
        )

        self.assertEqual(result.kind, BrainGuardResultKind.GOVERNOR_PROPOSAL)
        self.assertTrue(result.confirmation_required)
        self.assertEqual(result.actor_id, 123)
        self.assertEqual(result.idempotency_key, "discord:message:1")
        self.assertIsInstance(result.request, TaskCreateRequest)
        request = result.request
        assert isinstance(request, TaskCreateRequest)
        self.assertEqual(request.title, "엄마한테 전화")
        self.assertEqual(request.memo, "병원 끝나고")
        self.assertEqual(request.due_date, "2026-08-18")
        self.assertEqual(request.due_time, "10:00")
        self.assertEqual(request.profile, "main")

    def test_supplies_task_create_strips_due_and_uses_supplies_collection(self) -> None:
        result = adapt_kaosai_plan(
            {
                "intent": "task.create",
                "scope": "supplies",
                "parameters": {"title": "휴지", "memo": "코스트코", "dueDate": "2026-08-18", "dueTime": "14:00"},
            },
            self.context(),
        )

        self.assertIsInstance(result.request, TaskCreateRequest)
        request = result.request
        assert isinstance(request, TaskCreateRequest)
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(request.memo, "코스트코")
        self.assertEqual(request.collection_id, "supplies:abc")
        self.assertEqual(request.due_date, "")
        self.assertEqual(request.due_time, "")

    def test_supplies_due_update_is_rejected(self) -> None:
        with self.assertRaisesRegex(BrainGuardError, "supplies_due_date_not_allowed"):
            adapt_kaosai_plan(
                {
                    "intent": "task.update_due",
                    "scope": "supplies",
                    "parameters": {"taskTitle": "휴지", "dueDate": "2026-08-18"},
                },
                self.context(),
            )

    def test_task_due_update_plan_maps_to_governor_request(self) -> None:
        result = adapt_kaosai_plan(
            {
                "intent": "task.update_due",
                "scope": "family",
                "parameters": {"taskTitle": "영이 큐시미아", "dueDate": "2026-08-24", "dueTime": "10:00"},
            },
            self.context(),
        )

        self.assertIsInstance(result.request, TaskDueUpdateRequest)
        request = result.request
        assert isinstance(request, TaskDueUpdateRequest)
        self.assertEqual(request.profile, "family")
        self.assertEqual(request.task_title, "영이 큐시미아")
        self.assertEqual(request.due_date, "2026-08-24")

    def test_task_edit_plan_strips_supplies_due(self) -> None:
        result = adapt_kaosai_plan(
            {
                "intent": "task.edit",
                "scope": "supplies",
                "parameters": {
                    "taskTitle": "휴지",
                    "title": "두루마리 휴지",
                    "memo": "코스트코",
                    "dueDate": "2026-08-18",
                },
            },
            self.context(),
        )

        self.assertIsInstance(result.request, TaskEditRequest)
        request = result.request
        assert isinstance(request, TaskEditRequest)
        self.assertEqual(request.title, "두루마리 휴지")
        self.assertEqual(request.memo, "코스트코")
        self.assertEqual(request.due_date, "")

    def test_task_action_plan_maps_to_allowed_action(self) -> None:
        result = adapt_kaosai_plan(
            {"intent": "task.complete", "parameters": {"taskTitle": "엄마한테 전화"}},
            self.context(),
        )

        self.assertIsInstance(result.request, TaskActionRequest)
        request = result.request
        assert isinstance(request, TaskActionRequest)
        self.assertEqual(request.action, "complete")

    def test_event_create_plan_maps_to_family_event(self) -> None:
        result = adapt_kaosai_plan(
            {
                "intent": "event.create",
                "scope": "family",
                "parameters": {
                    "title": "엔소쿠료칸",
                    "startDate": "2026-08-15",
                    "allDay": True,
                    "memo": "포항 조사리",
                },
            },
            self.context(),
        )

        self.assertIsInstance(result.request, EventCreateRequest)
        request = result.request
        assert isinstance(request, EventCreateRequest)
        self.assertEqual(request.profile, "family")
        self.assertEqual(request.end_date, "2026-08-15")
        self.assertTrue(request.all_day)

    def test_memo_create_plan_maps_to_governor_request(self) -> None:
        result = adapt_kaosai_plan(
            {"intent": "memo.create", "parameters": {"content": "# RustDesk\n\n#server"}},
            self.context(),
        )

        self.assertIsInstance(result.request, MemoCreateRequest)
        request = result.request
        assert isinstance(request, MemoCreateRequest)
        self.assertEqual(request.content, "# RustDesk\n\n#server")

    def test_document_update_tags_plan_maps_to_governor_request(self) -> None:
        result = adapt_kaosai_plan(
            {
                "intent": "document.update_tags",
                "parameters": {"documentId": "42", "tags": ["#server", "rustdesk", "server"]},
            },
            self.context(),
        )

        self.assertIsInstance(result.request, DocumentTagRequest)
        request = result.request
        assert isinstance(request, DocumentTagRequest)
        self.assertTrue(result.confirmation_required)
        self.assertEqual(request.document_id, "42")
        self.assertEqual(request.tags, ("server", "rustdesk"))

    def test_document_update_tags_rejects_invalid_id_or_empty_tags(self) -> None:
        with self.assertRaisesRegex(BrainGuardError, "documentId_invalid"):
            adapt_kaosai_plan(
                {"intent": "document.update_tags", "parameters": {"documentId": "x", "tags": ["server"]}},
                self.context(),
            )
        with self.assertRaisesRegex(BrainGuardError, "tags_required"):
            adapt_kaosai_plan(
                {"intent": "document.update_tags", "parameters": {"documentId": "42", "tags": []}},
                self.context(),
            )

    def test_unknown_or_system_intent_is_rejected(self) -> None:
        for intent in ("system.restart", "shell.run", "docker.exec", "database.query"):
            with self.subTest(intent=intent):
                with self.assertRaisesRegex(BrainGuardError, "intent_not_allowed"):
                    adapt_kaosai_plan({"intent": intent, "parameters": {}}, self.context())

    def test_unknown_top_level_or_parameter_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(BrainGuardError, "plan_unknown_field"):
            adapt_kaosai_plan(
                {"intent": "memo.search", "parameters": {"query": "rustdesk"}, "tool": "governor"},
                self.context(),
            )
        for extra in ("collectionId", "url", "token", "shellCommand"):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(BrainGuardError, "memo.search.parameters_unknown_field"):
                    adapt_kaosai_plan(
                        {"intent": "memo.search", "parameters": {"query": "rustdesk", extra: "x"}},
                        self.context(),
                    )

    def test_invalid_date_and_scope_are_rejected(self) -> None:
        with self.assertRaisesRegex(BrainGuardError, "dueDate_invalid"):
            adapt_kaosai_plan(
                {"intent": "task.create", "parameters": {"title": "Call", "dueDate": "2026-99-99"}},
                self.context(),
            )
        with self.assertRaisesRegex(BrainGuardError, "scope_not_allowed"):
            adapt_kaosai_plan(
                {"intent": "memo.search", "scope": "system", "parameters": {"query": "rustdesk"}},
                self.context(),
            )


if __name__ == "__main__":
    unittest.main()
