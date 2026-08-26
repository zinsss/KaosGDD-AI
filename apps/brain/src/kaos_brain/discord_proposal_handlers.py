from __future__ import annotations

import logging
from typing import Any

import discord

from .brain_guard import BrainGuardResult, BrainGuardResultKind
from .discord_confirmation_views import (
    DocumentTagConfirmationView,
    EventCreateConfirmationView,
    MemoCreateConfirmationView,
    MemoDeleteConfirmationView,
    MemoEditConfirmationView,
)
from .discord_task_views import (
    TaskActionConfirmationView,
    TaskCreateConfirmationView,
    TaskEditConfirmationView,
    TaskUpdateConfirmationView,
)
from .discord_view_helpers import NO_MENTIONS, _reply_with_bound_view
from .event_intent import EventCreateRequest
from .governor_tools import (
    DocumentTagRequest,
    GovernorToolError,
    TaskEditRequest as GovernorTaskEditRequest,
    render_document_tags_proposal,
    render_event_create_proposal,
    render_memo_create_proposal,
    render_memo_delete_proposal,
    render_memo_edit_proposal,
    render_task_action_proposal,
    render_task_create_proposal,
    render_task_due_update_proposal,
)
from .kaos_ai import KaosAIError
from .memo_intent import MemoCreateRequest, MemoDeleteRequest, MemoEditRequest
from .task_update_intent import TaskActionRequest, TaskCreateRequest, TaskDueUpdateRequest, TaskTextEditRequest

LOGGER = logging.getLogger(__name__)


def _tool_unavailable() -> str:
    return "Governor 연결이 아직 없어요."


def _tool_failed(action: str) -> str:
    return f"{action} 실패했어요."


class BrainProposalMixin:
    governor_tools: Any
    settings: Any
    kaosai: Any

    async def _answer_with_guarded_plan(
        self,
        user_text: str,
        guarded: BrainGuardResult,
    ) -> tuple[str, discord.ui.View | None]:
        if guarded.kind is BrainGuardResultKind.READONLY_TOOL:
            return await self._answer_with_governor_tool(user_text, guarded.request, actor_id=guarded.actor_id)  # type: ignore[attr-defined,arg-type]
        if self.governor_tools is None:
            return _tool_unavailable(), None
        request = guarded.request
        try:
            if isinstance(request, TaskDueUpdateRequest):
                payload = await self.governor_tools.propose_task_due_update(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_task_due_update_proposal(payload),
                    TaskUpdateConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, TaskCreateRequest):
                payload = await self.governor_tools.propose_task_create(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_task_create_proposal(payload),
                    TaskCreateConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, TaskActionRequest):
                payload = await self.governor_tools.propose_task_action(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_task_action_proposal(payload),
                    TaskActionConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, GovernorTaskEditRequest):
                payload = await self.governor_tools.propose_task_edit(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_task_edit_proposal(payload),
                    TaskEditConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, EventCreateRequest):
                payload = await self.governor_tools.propose_event_create(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_event_create_proposal(payload),
                    EventCreateConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, MemoCreateRequest):
                payload = await self.governor_tools.propose_memo_create(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_memo_create_proposal(payload),
                    MemoCreateConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, MemoDeleteRequest):
                payload = await self.governor_tools.propose_memo_delete(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_memo_delete_proposal(payload),
                    MemoDeleteConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, MemoEditRequest):
                payload = await self.governor_tools.propose_memo_edit(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_memo_edit_proposal(payload),
                    MemoEditConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
            if isinstance(request, DocumentTagRequest):
                payload = await self.governor_tools.propose_document_tags(
                    request,
                    actor_id=guarded.actor_id,
                    idempotency_key=guarded.idempotency_key,
                )
                return (
                    render_document_tags_proposal(payload),
                    DocumentTagConfirmationView(self.governor_tools, guarded.actor_id, str(payload.get("confirmationId") or "")),
                )
        except GovernorToolError as exc:
            LOGGER.warning("Guarded Governor proposal failed intent=%s: %s", guarded.intent, exc)
            return _tool_failed("요청 처리"), None
        return _tool_failed("요청 처리"), None

    async def _propose_document_tag_suggestion(self, message: discord.Message, document_id: str) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        async with message.channel.typing():
            try:
                context = await self.governor_tools.get_document_tag_context(document_id)
                tags = await self.kaosai.suggest_document_tags(context)
                if not tags:
                    await message.reply(
                        "추천할 기존 태그를 못 찾았어요.",
                        mention_author=False,
                        allowed_mentions=NO_MENTIONS,
                    )
                    return
                payload = await self.governor_tools.propose_document_tags(
                    DocumentTagRequest(document_id, tags),
                    actor_id=int(message.author.id),
                    idempotency_key=f"discord:{message.id}:document-tags",
                )
            except (GovernorToolError, KaosAIError) as exc:
                LOGGER.warning("Document tag suggestion failed document_id=%s: %s", document_id, exc)
                await message.reply(
                    _tool_failed("문서 태그 추천"),
                    mention_author=False,
                    allowed_mentions=NO_MENTIONS,
                )
                return
        await message.reply(
            render_document_tags_proposal(payload)[: self.settings.max_reply_chars],
            view=DocumentTagConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_task_due_update(self, message: discord.Message, request: TaskDueUpdateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_task_due_update(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task due edit proposal failed: %s", exc)
            await message.reply(_tool_failed("할 일 수정"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_task_due_update_proposal(payload),
            view=TaskUpdateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )

    async def _propose_task_create(self, message: discord.Message, request: TaskCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_task_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task creation proposal failed: %s", exc)
            await message.reply(_tool_failed("할 일 저장"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_task_create_proposal(payload),
            view=TaskCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )

    async def _propose_task_action(self, message: discord.Message, request: TaskActionRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_task_action(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task action proposal failed: %s", exc)
            await message.reply(_tool_failed("할 일 변경"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_task_action_proposal(payload),
            view=TaskActionConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )

    async def _propose_task_edit(self, message: discord.Message, request: TaskTextEditRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_task_edit(
                GovernorTaskEditRequest(
                    request.task_title,
                    request.title,
                    request.memo,
                    due_date=request.due_date,
                    due_time=request.due_time,
                    priority=request.priority,
                    profile=request.profile,
                    collection_id=request.collection_id,
                ),
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task edit proposal failed: %s", exc)
            await message.reply(_tool_failed("할 일 수정"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_task_edit_proposal(payload),
            view=TaskEditConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )

    async def _propose_event_create(self, message: discord.Message, request: EventCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_event_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Event creation proposal failed: %s", exc)
            await message.reply(_tool_failed("일정 저장"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_event_create_proposal(payload),
            view=EventCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )

    async def _propose_memo_create(self, message: discord.Message, request: MemoCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_memo_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Memo creation proposal failed: %s", exc)
            await message.reply(_tool_failed("메모 저장"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_memo_create_proposal(payload),
            view=MemoCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )

    async def _propose_memo_delete(self, message: discord.Message, request: MemoDeleteRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_memo_delete(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Memo delete proposal failed: %s", exc)
            await message.reply(_tool_failed("메모 삭제"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_memo_delete_proposal(payload),
            view=MemoDeleteConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )

    async def _propose_memo_edit(self, message: discord.Message, request: MemoEditRequest) -> None:
        if self.governor_tools is None:
            await message.reply(_tool_unavailable(), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        try:
            payload = await self.governor_tools.propose_memo_edit(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Memo edit proposal failed: %s", exc)
            await message.reply(_tool_failed("메모 수정"), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await _reply_with_bound_view(
            message,
            render_memo_edit_proposal(payload),
            view=MemoEditConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
        )
