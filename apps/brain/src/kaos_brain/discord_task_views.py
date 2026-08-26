from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any

import discord

from .discord_formatting import (
    ACTIVE_TASKS_TITLE,
    KST,
    SEARCH_RESULT_LIMIT,
    SUPPLIES_HISTORY_TITLE,
    SUPPLIES_TITLE,
    TASKS_HISTORY_TITLE,
    TASK_SERVICE_HISTORY_LIMIT,
    TASK_SERVICE_PAGE_SIZE,
    _has_overdue_tasks,
    _month_end,
    _render_active_task_selection,
    _render_completed_task_selection,
    _render_task_service_message,
    _shift_date_month,
    _task_option_description,
    _task_option_label,
    _task_results,
    _uses_supplies_request,
)
from .discord_view_helpers import (
    NO_MENTIONS,
    BrainAutoClosingView,
    _defer_component_update,
    _edit_deferred_component,
    _followup_with_bound_view,
)
from .governor_tools import (
    GovernorToolClient,
    GovernorToolError,
    TaskEditRequest as GovernorTaskEditRequest,
    render_task_action_completed,
    render_task_action_proposal,
    render_task_create_completed,
    render_task_create_proposal,
    render_task_due_update_completed,
    render_task_edit_completed,
    render_task_edit_proposal,
)
from .task_update_intent import TaskActionRequest, TaskCreateRequest
from .tool_intent import ToolKind, ToolRequest

LOGGER = logging.getLogger(__name__)


def _tool_failed(action: str) -> str:
    return f"{action} 실패했어요."


def _tool_cancelled(action: str) -> str:
    return f"{action} 취소했어요."


class BrainCompletedTasksView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, tasks: list[dict[str, Any]]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.tasks = tasks[:SEARCH_RESULT_LIMIT]
        self.add_item(BrainCompletedTasksSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainCompletedTasksSelect(discord.ui.Select):
    def __init__(self, parent: BrainCompletedTasksView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(task) or None,
                value=str(index),
            )
            for index, task in enumerate(parent.tasks)
        ]
        super().__init__(placeholder="Reopen completed item", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            task = self.parent_view.tasks[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
            payload = await self.parent_view.governor_tools.propose_task_action(
                TaskActionRequest(
                    title,
                    "reopen",
                    profile=self.parent_view.request.profile,
                    collection_id=self.parent_view.request.collection_id,
                    uid=str(task.get("uid") or ""),
                ),
                actor_id=self.parent_view.actor_id,
                idempotency_key=f"brain-task-reopen-{interaction.id}",
            )
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Task reopen failed: %s", exc)
            await interaction.response.send_message(_tool_failed("할 일 다시 열기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            render_task_action_proposal(payload),
            view=TaskActionConfirmationView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                str(payload.get("confirmationId") or ""),
            ),
        )


class BrainActiveTasksView(discord.ui.View):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        request: ToolRequest,
        tasks: list[dict[str, Any]],
        *,
        mode: str = "active",
        page: int = 0,
        month: date | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.tasks = tasks
        self.mode = "history" if mode == "history" else "active"
        self.page = max(0, page)
        self.month = (month or datetime.now(KST).date()).replace(day=1)
        self._rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @property
    def supplies(self) -> bool:
        return _uses_supplies_request(self.request)

    @property
    def title(self) -> str:
        if self.mode == "history":
            return SUPPLIES_HISTORY_TITLE if self.supplies else TASKS_HISTORY_TITLE
        return SUPPLIES_TITLE if self.supplies else ACTIVE_TASKS_TITLE

    @property
    def page_tasks(self) -> list[dict[str, Any]]:
        start = self.page * TASK_SERVICE_PAGE_SIZE
        return self.tasks[start : start + TASK_SERVICE_PAGE_SIZE]

    @property
    def max_page(self) -> int:
        if not self.tasks:
            return 0
        return (len(self.tasks) - 1) // TASK_SERVICE_PAGE_SIZE

    def content(self) -> str:
        return _render_task_service_message(
            self.title,
            self.tasks,
            page=self.page,
            history=self.mode == "history",
            supplies=self.supplies,
            month=self.month,
        )

    def _rebuild_items(self) -> None:
        self.clear_items()
        if self.page > self.max_page:
            self.page = self.max_page
        if self.mode == "history":
            if self.page_tasks:
                self.add_item(BrainTaskHistorySelect(self))
            self.add_item(BrainTaskServiceMonthButton("<<", -1))
            self.add_item(BrainTaskServicePageButton("←", -1, disabled=self.page <= 0))
            self.add_item(BrainTaskServicePageStatusButton(self.page, self.max_page))
            self.add_item(BrainTaskServicePageButton("→", 1, disabled=self.page >= self.max_page))
            self.add_item(BrainTaskServiceMonthButton(">>", 1))
            self.add_item(BrainTaskServiceModeButton("Active"))
            self.add_item(BrainTaskServiceCloseButton())
            return
        if self.page_tasks:
            self.add_item(BrainActiveTasksSelect(self))
        self.add_item(BrainTaskServicePageButton("←", -1, disabled=self.page <= 0))
        self.add_item(BrainTaskServicePageStatusButton(self.page, self.max_page))
        self.add_item(BrainTaskServicePageButton("→", 1, disabled=self.page >= self.max_page))
        self.add_item(BrainTaskServiceModeButton("History"))
        self.add_item(BrainTaskServiceCloseButton())

    async def edit_message(self, interaction: discord.Interaction) -> None:
        self._rebuild_items()
        await interaction.edit_original_response(content=self.content(), view=self)

    async def fetch_history(self, *, month: date | None = None, page: int = 0) -> "BrainActiveTasksView":
        month_start = (month or self.month).replace(day=1)
        month_end = _month_end(month_start)
        request = ToolRequest(
            ToolKind.COMPLETED_TASKS,
            profile=self.request.profile,
            collection_id=self.request.collection_id,
            start=month_start.isoformat(),
            end=month_end.isoformat(),
        )
        payload = await self.governor_tools.completed_tasks(request, limit=TASK_SERVICE_HISTORY_LIMIT)
        return BrainActiveTasksView(
            self.governor_tools,
            self.actor_id,
            request,
            _task_results(payload),
            mode="history",
            page=page,
            month=month_start,
        )

    async def fetch_active(self) -> "BrainActiveTasksView":
        request = ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.request.profile, collection_id=self.request.collection_id)
        payload = await self.governor_tools.fetch(request)
        return BrainActiveTasksView(self.governor_tools, self.actor_id, request, _task_results(payload), mode="active")


class BrainActiveTasksSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveTasksView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(
                    task,
                    include_completed=False,
                    supplies=_uses_supplies_request(parent.request),
                )
                or None,
                value=str(index),
            )
            for index, task in enumerate(parent.page_tasks)
        ]
        start = parent.page * TASK_SERVICE_PAGE_SIZE + 1
        end = start + len(parent.page_tasks) - 1
        label = "Supplies" if parent.supplies else "Active Tasks"
        placeholder = f"{label} {start}-{end}"
        if not parent.supplies and _has_overdue_tasks(parent.tasks):
            placeholder = f"{placeholder} ★"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            task = self.parent_view.page_tasks[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Task selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("할 일 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            f"## {title}",
            view=BrainActiveTaskActionsView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                self.parent_view.request,
                task,
            ),
        )


class BrainTaskHistorySelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveTasksView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(task, supplies=parent.supplies) or None,
                value=str(index),
            )
            for index, task in enumerate(parent.page_tasks)
        ]
        start = parent.page * TASK_SERVICE_PAGE_SIZE + 1
        end = start + len(parent.page_tasks) - 1
        label = "Completed Supplies" if parent.supplies else "Completed Tasks"
        super().__init__(placeholder=f"{label} {start}-{end}", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            task = self.parent_view.page_tasks[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Completed task selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("완료 할 일 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            _render_completed_task_selection(title, task, supplies=self.parent_view.supplies),
            view=BrainCompletedTaskActionsView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                self.parent_view.request,
                task,
            ),
        )


class BrainTaskServicePageButton(discord.ui.Button):
    def __init__(self, label: str, delta: int, *, disabled: bool = False) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1, disabled=disabled)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, BrainActiveTasksView):
            await interaction.response.send_message("View unavailable.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        view.page = min(max(view.page + self.delta, 0), view.max_page)
        await view.edit_message(interaction)


class BrainTaskServicePageStatusButton(discord.ui.Button):
    def __init__(self, page: int, max_page: int) -> None:
        super().__init__(
            label=f"Page {page + 1}/{max_page + 1}",
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=True,
        )


class BrainTaskServiceMonthButton(discord.ui.Button):
    def __init__(self, label: str, delta: int) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, BrainActiveTasksView):
            await interaction.response.send_message("View unavailable.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        try:
            next_view = await view.fetch_history(month=_shift_date_month(view.month, self.delta), page=0)
        except GovernorToolError as exc:
            LOGGER.warning("Task history month failed: %s", exc)
            await interaction.followup.send(_tool_failed("완료 목록 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.edit_original_response(content=next_view.content(), view=next_view)


class BrainTaskServiceModeButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary if label == "Active" else discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, BrainActiveTasksView):
            await interaction.response.send_message("View unavailable.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        try:
            next_view = await view.fetch_active() if self.label == "Active" else await view.fetch_history(page=0)
        except GovernorToolError as exc:
            LOGGER.warning("Task service mode switch failed: %s", exc)
            await interaction.followup.send(_tool_failed("할 일 목록 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.edit_original_response(content=next_view.content(), view=next_view)


class BrainTaskServiceCloseButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Close", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()


class BrainActiveTaskActionsView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, task: dict[str, Any]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.task = task
        self.title = str(task.get("title") or task.get("summary") or "").strip()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._propose(interaction, "complete")

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BrainTaskEditModal(self.governor_tools, self.actor_id, self.request, self.task))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._propose(interaction, "delete")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()

    async def _propose(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.propose_task_action(
                TaskActionRequest(
                    self.title,
                    action,
                    profile=self.request.profile,
                    collection_id=self.request.collection_id,
                    uid=str(self.task.get("uid") or ""),
                ),
                actor_id=self.actor_id,
                idempotency_key=f"brain-task-{action}-{interaction.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task action failed action=%s: %s", action, exc)
            await interaction.followup.send(_tool_failed("할 일 변경"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.edit_original_response(
            content=render_task_action_proposal(payload),
            view=TaskActionConfirmationView(self.governor_tools, self.actor_id, str(payload.get("confirmationId") or "")),
            allowed_mentions=NO_MENTIONS,
        )
        self.stop()


class BrainCompletedTaskActionsView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, task: dict[str, Any]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.task = task
        self.title = str(task.get("title") or task.get("summary") or "").strip()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Undo", style=discord.ButtonStyle.success)
    async def undo(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._propose_action(interaction, "reopen")

    @discord.ui.button(label="Make New", style=discord.ButtonStyle.primary)
    async def make_new(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.propose_task_create(
                TaskCreateRequest(
                    self.title,
                    "",
                    "",
                    profile=self.request.profile,
                    collection_id=self.request.collection_id,
                ),
                actor_id=self.actor_id,
                idempotency_key=f"brain-task-make-new-{interaction.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Completed task make-new failed: %s", exc)
            await interaction.followup.send(_tool_failed("할 일 다시 만들기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.edit_original_response(
            content=render_task_create_proposal(payload),
            view=TaskCreateConfirmationView(self.governor_tools, self.actor_id, str(payload.get("confirmationId") or "")),
            allowed_mentions=NO_MENTIONS,
        )
        self.stop()

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._propose_action(interaction, "delete")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()

    async def _propose_action(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.propose_task_action(
                TaskActionRequest(
                    self.title,
                    action,
                    profile=self.request.profile,
                    collection_id=self.request.collection_id,
                    uid=str(self.task.get("uid") or ""),
                ),
                actor_id=self.actor_id,
                idempotency_key=f"brain-task-{action}-{interaction.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Completed task action failed action=%s: %s", action, exc)
            await interaction.followup.send(_tool_failed("완료 할 일 변경"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.edit_original_response(
            content=render_task_action_proposal(payload),
            view=TaskActionConfirmationView(self.governor_tools, self.actor_id, str(payload.get("confirmationId") or "")),
            allowed_mentions=NO_MENTIONS,
        )
        self.stop()


class BrainTaskEditModal(discord.ui.Modal):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, task: dict[str, Any]) -> None:
        super().__init__(title="Edit 비품" if _uses_supplies_request(request) else "Edit Task", timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.task = task
        self.title_input = discord.ui.TextInput(
            label="Title",
            style=discord.TextStyle.short,
            required=True,
            default=str(task.get("title") or task.get("summary") or "")[:100],
            max_length=100,
        )
        self.memo_input = discord.ui.TextInput(
            label="Memo",
            style=discord.TextStyle.paragraph,
            required=False,
            default=str(task.get("memo") or task.get("description") or "")[:1000],
            max_length=1000,
        )
        self.add_item(self.title_input)
        self.add_item(self.memo_input)
        if not _uses_supplies_request(request):
            self.due_date_input = discord.ui.TextInput(
                label="Due date",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("due") or "")[:10],
                placeholder="yyyy-mm-dd",
                max_length=10,
            )
            self.due_time_input = discord.ui.TextInput(
                label="Due time",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("dueTime") or "")[:5],
                placeholder="HH:MM",
                max_length=5,
            )
            self.priority_input = discord.ui.TextInput(
                label="Priority",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("priority") or "")[:1],
                placeholder="blank, 1, 5, or 9",
                max_length=1,
            )
            self.add_item(self.due_date_input)
            self.add_item(self.due_time_input)
            self.add_item(self.priority_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        old_title = str(self.task.get("title") or self.task.get("summary") or "").strip()
        due_date = str(getattr(self, "due_date_input", _EmptyInput()).value or "")
        due_time = str(getattr(self, "due_time_input", _EmptyInput()).value or "")
        priority = str(getattr(self, "priority_input", _EmptyInput()).value or "")
        try:
            payload = await self.governor_tools.propose_task_edit(
                GovernorTaskEditRequest(
                    old_title,
                    str(self.title_input.value or ""),
                    str(self.memo_input.value or ""),
                    due_date=due_date,
                    due_time=due_time,
                    priority=priority,
                    profile=self.request.profile,
                    collection_id=self.request.collection_id,
                    uid=str(self.task.get("uid") or ""),
                ),
                actor_id=self.actor_id,
                idempotency_key=f"brain-task-edit-{interaction.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task edit proposal failed: %s", exc)
            await interaction.response.send_message(_tool_failed("할 일 수정"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.send_message(
            render_task_edit_proposal(payload),
            view=TaskEditConfirmationView(self.governor_tools, self.actor_id, str(payload.get("confirmationId") or "")),
            allowed_mentions=NO_MENTIONS,
        )


class _EmptyInput:
    value = ""


class TaskEditConfirmationView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_edit_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Task edit approval failed: %s", exc)
            content = _tool_failed("할 일 수정")
        for item in self.children:
            item.disabled = True
        await _edit_deferred_component(interaction, content=content, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("할 일 수정"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class TaskUpdateConfirmationView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_due_update_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Task due edit approval failed: %s", exc)
            content = _tool_failed("할 일 수정")
        for item in self.children:
            item.disabled = True
        await _edit_deferred_component(interaction, content=content, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("할 일 수정"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class TaskCreateConfirmationView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_create_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Task creation approval failed: %s", exc)
            content = _tool_failed("할 일 저장")
        await _edit_deferred_component(interaction, content=content, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("할 일 저장"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class TaskActionConfirmationView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_action_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Task action approval failed: %s", exc)
            content = _tool_failed("할 일 변경")
        await _edit_deferred_component(interaction, content=content, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("할 일 변경"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

