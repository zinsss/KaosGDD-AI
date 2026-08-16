from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_brain.bot import (
    BrainActiveTaskActionsView,
    BrainActiveTasksSelect,
    BrainActiveTasksView,
    BrainTaskEditModal,
    BrainCompletedTasksSelect,
    BrainCompletedTasksView,
    BrainDocumentSearchSelect,
    BrainDocumentSearchView,
    BrainMemoDeleteConfirmView,
    BrainMemoEditConfirmView,
    BrainMemoSearchSelect,
    BrainMemoSearchView,
)
from kaos_brain.tool_intent import ToolKind, ToolRequest


class FakeGovernorTools:
    def __init__(self) -> None:
        self.task_action_calls = []
        self.task_edit_calls = []

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


class BrainBotViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_memo_search_select_opens_selected_memo_as_new_message(self) -> None:
        view = BrainMemoSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "rustdesk",
            [{"name": "memos/42", "snippet": "# Rustdesk", "tags": ["server"]}],
        )
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

    async def test_document_search_select_opens_selected_document_as_new_message(self) -> None:
        view = BrainDocumentSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "보험",
            [{"id": 42, "title": "Insurance"}],
        )
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
        self.assertIn("## Documents search · 보험", content)
        self.assertIn("Insurance receipt", content)

    def test_memo_confirm_buttons_match_governor_labels(self) -> None:
        edit = BrainMemoEditConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]
        delete = BrainMemoDeleteConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]

        self.assertEqual([item.label for item in edit.children], ["Edit Memo", "Cancel"])
        self.assertEqual([item.label for item in delete.children], ["Delete Memo", "Cancel"])

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


if __name__ == "__main__":
    unittest.main()
