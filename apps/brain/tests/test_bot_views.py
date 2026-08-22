from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_brain.bot import (
    BrainActiveControlSelect,
    BrainActiveControlView,
    BrainActiveTaskActionsView,
    BrainActiveTasksSelect,
    BrainActiveTasksView,
    BrainDeletedMemoView,
    BrainTaskEditModal,
    BrainCompletedTasksSelect,
    BrainCompletedTasksView,
    BrainDocumentSearchSelect,
    BrainDocumentSearchView,
    BrainMemoDeleteConfirmView,
    BrainMemoEditConfirmView,
    BrainOpenedDocumentView,
    BrainMemoSearchSelect,
    BrainMemoSearchView,
    TaskCreateConfirmationView,
    render_active_control_message,
)
from kaos_brain.tool_intent import ToolKind, ToolRequest


class FakeGovernorTools:
    def __init__(self) -> None:
        self.task_action_calls = []
        self.task_edit_calls = []
        self.approve_calls = []

    async def get_memo(self, name: str):
        return {"memo": {"name": name, "content": "# Rustdesk\nUse Tailscale."}}

    async def get_document(self, document_id: object):
        return {
            "document": {
                "id": document_id,
                "title": "Insurance receipt",
                "filename": "receipt.pdf",
                "correspondent": "Clinic",
            }
        }

    async def propose_task_action(self, request, *, actor_id: int, idempotency_key: str):
        self.task_action_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-1",
            "task": {
                "title": request.task_title,
                "action": request.action,
                "due": "",
                "dueTime": "",
            },
        }

    async def propose_task_edit(self, request, *, actor_id: int, idempotency_key: str):
        self.task_edit_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-edit-1",
            "task": {
                "oldTitle": request.task_title,
                "title": request.title,
                "oldDue": "",
                "oldDueTime": "",
                "due": request.due_date,
                "dueTime": request.due_time,
            },
        }

    async def approve_confirmation(self, confirmation_id: str, *, actor_id: int):
        self.approve_calls.append((confirmation_id, actor_id))
        return {"task": {"title": "오도리 문고리", "due": "", "dueTime": ""}}

    async def fetch(self, request):
        if request.profile == "supplies":
            return {"tasks": [{"title": "토프라민"}]}
        return {"tasks": [{"title": "로운이 제로이드", "due": "2026-08-22", "dueTime": "10:00"}]}

    async def propose_memo_create(self, request, *, actor_id: int, idempotency_key: str):
        return {"confirmationId": "confirm-memo-create", "memo": {"content": request.content}}

    async def propose_memo_delete_by_name(self, name: str, *, actor_id: int, idempotency_key: str):
        return {"confirmationId": "confirm-memo-delete", "memo": {"name": name}}


class BrainBotViewTests(unittest.IsolatedAsyncioTestCase):
    def active_control_settings(self):
        return SimpleNamespace(
            guild_id=100,
            brain_channel_id=300,
            allowed_user_ids=frozenset({200}),
            governor_tools_profile="main",
            governor_tools_supplies_collection_id="supplies:abc",
        )

    def test_active_control_message_summarizes_tasks_and_supplies(self) -> None:
        content = render_active_control_message(
            [{"title": "Task"}],
            [{"title": "Supply"}],
        )

        self.assertEqual(content, "## Active\n- Tasks: 1 active\n- Supplies: 1 active")

    async def test_active_control_select_opens_existing_action_view(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [{"title": "로운이 제로이드", "due": "2026-08-22", "dueTime": "10:00"}],
            [{"title": "토프라민"}],
        )
        task_select = next(
            child
            for child in view.children
            if isinstance(child, BrainActiveControlSelect) and child.kind == "tasks"
        )
        task_select._values = ["0"]
        interaction = SimpleNamespace(
            id=700,
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await task_select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn("## 로운이 제로이드", content)
        self.assertIn("- due: 2026-08-22 10:00", content)
        action_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(action_view, BrainActiveTaskActionsView)
        self.assertEqual([item.label for item in action_view.children], ["Complete", "Edit", "Delete", "Close"])

    async def test_active_control_refresh_rebuilds_dropdowns(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [],
            [],
        )
        refresh = next(child for child in view.children if getattr(child, "label", "") == "Refresh")
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await refresh.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        interaction.edit_original_response.assert_awaited_once()
        self.assertIn("Tasks: 1 active", interaction.edit_original_response.await_args.kwargs["content"])
        refreshed = interaction.edit_original_response.await_args.kwargs["view"]
        self.assertEqual(
            [child.placeholder for child in refreshed.children if isinstance(child, BrainActiveControlSelect)],
            ["Active tasks", "Active supplies"],
        )

    async def test_memo_search_select_opens_selected_memo_as_new_message(self) -> None:
        view = BrainMemoSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "rustdesk",
            [{"name": "memos/42", "snippet": "# Rustdesk", "tags": ["server"]}],
        )
        search_message = SimpleNamespace(id=900, delete=AsyncMock())
        view.bind_message(search_message)  # type: ignore[arg-type]
        select = next(child for child in view.children if isinstance(child, BrainMemoSearchSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertEqual(content, "# Rustdesk\nUse Tailscale.")
        self.assertIn("view", interaction.followup.send.await_args.kwargs)
        search_message.delete.assert_awaited_once()

    async def test_document_search_select_opens_selected_document_as_new_message(self) -> None:
        view = BrainDocumentSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "보험",
            [{"id": 42, "title": "Insurance"}],
            paperless_public_url="https://paperless.example",
        )
        search_message = SimpleNamespace(id=901, delete=AsyncMock())
        view.bind_message(search_message)  # type: ignore[arg-type]
        select = next(child for child in view.children if isinstance(child, BrainDocumentSearchSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn("## Insurance receipt", content)
        self.assertNotIn("Documents search", content)
        self.assertIn("Insurance receipt", content)
        opened_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(opened_view, BrainOpenedDocumentView)
        self.assertEqual([item.label for item in opened_view.children], ["Close", "Open document"])
        search_message.delete.assert_awaited_once()

    async def test_brain_search_window_shows_expired_notice_on_timeout(self) -> None:
        view = BrainMemoSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "rustdesk",
            [{"name": "memos/42", "snippet": "# Rustdesk"}],
        )
        search_message = SimpleNamespace(id=902, edit=AsyncMock())
        view.bind_message(search_message)  # type: ignore[arg-type]

        await view.on_timeout()

        search_message.edit.assert_awaited_once()
        self.assertEqual(
            search_message.edit.await_args.kwargs["content"],
            "Search result of rustdesk expired after 10 mins.",
        )
        self.assertIsNone(search_message.edit.await_args.kwargs["view"])

    def test_memo_confirm_buttons_match_governor_labels(self) -> None:
        edit = BrainMemoEditConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]
        delete = BrainMemoDeleteConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]

        self.assertEqual([item.label for item in edit.children], ["Edit Memo", "Cancel"])
        self.assertEqual([item.label for item in delete.children], ["Delete Memo", "Cancel"])

    async def test_memo_delete_confirm_defers_before_governor_write(self) -> None:
        tools = FakeGovernorTools()
        view = BrainMemoDeleteConfirmView(tools, 200, "memos/42", "# Memo")  # type: ignore[arg-type]
        order: list[str] = []

        async def defer() -> None:
            order.append("defer")

        async def propose_memo_delete_by_name(name: str, *, actor_id: int, idempotency_key: str):
            order.append("propose")
            return {"confirmationId": "confirm-memo-delete", "memo": {"name": name}}

        tools.propose_memo_delete_by_name = propose_memo_delete_by_name  # type: ignore[method-assign]
        interaction = SimpleNamespace(
            id=1003,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(side_effect=defer), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(order, ["defer", "propose"])
        interaction.edit_original_response.assert_awaited_once()
        self.assertIn("Deleted at", interaction.edit_original_response.await_args.kwargs["content"])

    async def test_memo_undo_delete_defers_before_governor_write(self) -> None:
        tools = FakeGovernorTools()
        view = BrainDeletedMemoView(tools, 200, "# Memo")  # type: ignore[arg-type]
        order: list[str] = []

        async def defer() -> None:
            order.append("defer")

        async def propose_memo_create(request, *, actor_id: int, idempotency_key: str):
            order.append("propose")
            return {"confirmationId": "confirm-memo-create", "memo": {"content": request.content}}

        tools.propose_memo_create = propose_memo_create  # type: ignore[method-assign]
        interaction = SimpleNamespace(
            id=1004,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(side_effect=defer), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(order, ["defer", "propose"])
        interaction.edit_original_response.assert_awaited_once()
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["content"], "# Memo")

    async def test_completed_task_select_sends_reopen_confirmation_message(self) -> None:
        tools = FakeGovernorTools()
        view = BrainCompletedTasksView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.COMPLETED_TASKS, profile="supplies"),
            [{"title": "Soap", "completedDate": "2026-08-15"}],
        )
        select = next(child for child in view.children if isinstance(child, BrainCompletedTasksSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            id=777,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        request, actor_id, idempotency_key = tools.task_action_calls[0]
        self.assertEqual(request.task_title, "Soap")
        self.assertEqual(request.action, "reopen")
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "brain-task-reopen-777")
        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn("## Confirm task action", content)
        self.assertIn("- action: reopen", content)

    async def test_active_task_select_sends_action_buttons(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTasksView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            [{"title": "Soap"}],
        )
        select = next(child for child in view.children if isinstance(child, BrainActiveTasksSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            id=888,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        self.assertEqual(interaction.followup.send.await_args.args[0], "## Soap")
        action_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(action_view, BrainActiveTaskActionsView)
        self.assertEqual([item.label for item in action_view.children], ["Complete", "Edit", "Delete", "Close"])

    async def test_active_task_complete_button_sends_confirmation(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTaskActionsView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"uid": "TASK-1", "title": "Call mom"},
        )
        interaction = SimpleNamespace(
            id=999,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        request, actor_id, idempotency_key = tools.task_action_calls[0]
        self.assertEqual(request.task_title, "Call mom")
        self.assertEqual(request.action, "complete")
        self.assertEqual(request.profile, "family")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "brain-task-complete-999")
        content = interaction.response.edit_message.await_args.kwargs["content"]
        self.assertIn("## Confirm task action", content)
        self.assertIn("- action: complete", content)

    async def test_active_task_delete_button_sends_confirmation(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTaskActionsView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            {"uid": "SUPPLY-1", "title": "Soap"},
        )
        interaction = SimpleNamespace(
            id=1000,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )

        await view.children[2].callback(interaction)  # type: ignore[arg-type,union-attr]

        request, _, idempotency_key = tools.task_action_calls[0]
        self.assertEqual(request.task_title, "Soap")
        self.assertEqual(request.action, "delete")
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(idempotency_key, "brain-task-delete-1000")

    async def test_active_task_edit_button_opens_prefilled_modal(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTaskActionsView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"uid": "TASK-1", "title": "Call mom", "memo": "weekly", "due": "2026-08-17", "dueTime": "10:00"},
        )
        interaction = SimpleNamespace(
            id=1001,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock()),
        )

        await view.children[1].callback(interaction)  # type: ignore[arg-type,union-attr]

        modal = interaction.response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, BrainTaskEditModal)
        self.assertEqual(len(modal.children), 5)
        self.assertEqual(str(modal.title_input.default), "Call mom")
        self.assertEqual(str(modal.memo_input.default), "weekly")

    async def test_supplies_edit_modal_has_no_due_fields(self) -> None:
        modal = BrainTaskEditModal(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            {"uid": "SUPPLY-1", "title": "Soap", "memo": "bath"},
        )

        self.assertEqual(len(modal.children), 2)

    async def test_task_edit_modal_sends_confirmation(self) -> None:
        tools = FakeGovernorTools()
        modal = BrainTaskEditModal(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"uid": "TASK-1", "title": "Call mom", "memo": "weekly", "due": "2026-08-17", "dueTime": "10:00"},
        )
        modal.title_input._value = "Call dad"
        modal.memo_input._value = "monthly"
        modal.due_date_input._value = "2026-08-20"
        modal.due_time_input._value = "14:30"
        modal.priority_input._value = "1"
        interaction = SimpleNamespace(
            id=1002,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        await modal.on_submit(interaction)  # type: ignore[arg-type]

        request, actor_id, idempotency_key = tools.task_edit_calls[0]
        self.assertEqual(request.uid, "TASK-1")
        self.assertEqual(request.task_title, "Call mom")
        self.assertEqual(request.title, "Call dad")
        self.assertEqual(request.memo, "monthly")
        self.assertEqual(request.due_date, "2026-08-20")
        self.assertEqual(request.due_time, "14:30")
        self.assertEqual(request.priority, "1")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "brain-task-edit-1002")
        content = interaction.response.send_message.await_args.args[0]
        self.assertIn("## Confirm task edit", content)

    async def test_task_create_confirm_defers_before_approving(self) -> None:
        tools = FakeGovernorTools()
        view = TaskCreateConfirmationView(tools, 200, "confirm-create-1")  # type: ignore[arg-type]
        order: list[str] = []

        async def defer() -> None:
            order.append("defer")

        async def approve_confirmation(confirmation_id: str, *, actor_id: int):
            order.append("approve")
            return {"task": {"title": "오도리 문고리", "due": "", "dueTime": ""}}

        tools.approve_confirmation = approve_confirmation  # type: ignore[method-assign]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(side_effect=defer), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(order, ["defer", "approve"])
        interaction.edit_original_response.assert_awaited_once()
        content = interaction.edit_original_response.await_args.kwargs["content"]
        self.assertEqual(content, "Task added.")
        self.assertIsNone(interaction.edit_original_response.await_args.kwargs["view"])


if __name__ == "__main__":
    unittest.main()
