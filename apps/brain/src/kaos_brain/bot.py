from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

import discord

from .brain_guard import BrainGuardContext, BrainGuardError, BrainGuardResult, BrainGuardResultKind, adapt_kaosai_plan
from .config import Settings
from .event_intent import EventCreateRequest, parse_event_create
from .governor_tools import (
    DocumentTagRequest,
    GovernorToolClient,
    GovernorToolConfig,
    GovernorToolError,
    TaskEditRequest as GovernorTaskEditRequest,
    document_public_url,
    document_option_description,
    document_option_label,
    memo_option_description,
    memo_option_label,
    render_memo_create_completed,
    render_memo_create_proposal,
    render_memo_delete_completed,
    render_memo_delete_proposal,
    render_memo_deleted,
    render_memo_edit_completed,
    render_memo_edit_proposal,
    render_document_opened,
    render_document_tags_completed,
    render_document_tags_proposal,
    render_event_create_completed,
    render_event_create_proposal,
    render_memo_opened,
    render_combined_search_context,
    render_task_action_completed,
    render_task_action_proposal,
    render_task_create_completed,
    render_task_create_proposal,
    render_task_edit_completed,
    render_task_edit_proposal,
    render_task_due_update_completed,
    render_task_due_update_proposal,
    render_tool_context,
    search_results,
)
from .intent import Route, parse_request
from .kaos_ai import DisabledKaosAIPlanner, KaosAIConfig, KaosAIError, KaosAIPlanner, OpenClawKaosAIPlanner
from .memo_intent import MemoCreateRequest, MemoDeleteRequest, MemoEditRequest, parse_memo_create, parse_memo_delete, parse_memo_edit
from .ollama import OllamaClient, OllamaConfig, OllamaError
from .reauth import OpenClawReauthClient, ReauthConfig, ReauthError
from .task_update_intent import (
    TaskActionRequest,
    TaskCreateRequest,
    TaskDueUpdateRequest,
    TaskTextEditRequest,
    parse_task_action,
    parse_task_create,
    parse_task_edit,
    parse_task_due_update,
)
from .tool_intent import ToolKind, ToolRequest, parse_tool_request

LOGGER = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()
KST = ZoneInfo("Asia/Seoul")
DOCUMENT_TAG_SUGGESTION_PATTERN = re.compile(r"\b(?:document|doc|문서)?\s*(\d{1,9})\b")
BRAIN_SEARCH_WINDOW_SECONDS = 600
OPENAI_CALLBACK_PREFIX = "http://localhost:1455/auth/callback?"
OPENAI_CODE_PATTERN = re.compile(r"^ac_[A-Za-z0-9_.-]+$")
ACTIVE_CONTROL_MARKER = "## Active"
ACTIVE_CONTROL_LIMIT = 25


def _bind_view_message(view: discord.ui.View | None, message: discord.Message) -> None:
    bind = getattr(view, "bind_message", None)
    if callable(bind):
        bind(message)


async def _defer_component_update(interaction: discord.Interaction) -> None:
    await interaction.response.defer()


async def _edit_deferred_component(
    interaction: discord.Interaction,
    *,
    content: str,
    view: discord.ui.View | None,
) -> None:
    await interaction.edit_original_response(content=content, view=view, allowed_mentions=NO_MENTIONS)


def _kaosai_planner_from_settings(settings: Settings) -> KaosAIPlanner:
    if not settings.kaosai_enabled:
        return DisabledKaosAIPlanner()
    if settings.kaosai_provider == "openclaw":
        return OpenClawKaosAIPlanner(
            KaosAIConfig(
                enabled=True,
                provider=settings.kaosai_provider,
                base_url=settings.kaosai_base_url,
                model=settings.kaosai_model,
                api_token=settings.kaosai_api_token,
                timeout_seconds=settings.kaosai_timeout_seconds,
            )
        )
    return DisabledKaosAIPlanner()


def _tool_unavailable() -> str:
    return "Governor 연결이 아직 없어요."


def _tool_failed(action: str) -> str:
    return f"{action} 실패했어요."


def _tool_cancelled(action: str) -> str:
    return f"{action} 취소했어요."


def _is_openai_callback(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(OPENAI_CALLBACK_PREFIX) or bool(OPENAI_CODE_PATTERN.match(stripped))


def _is_kaosai_reauth_command(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {
        "ai:reauth",
        "kaosai reauth",
        "kaosai login",
        "chatgpt reauth",
        "chatgpt login",
        "openclaw reauth",
    }


def _looks_like_auth_failure(text: str) -> bool:
    lowered = text.lower()
    return "token_expired" in lowered or "authentication failed" in lowered or "401" in lowered


async def _start_reauth_message(reauth: OpenClawReauthClient) -> str:
    try:
        payload = await reauth.start()
    except ReauthError as exc:
        return f"KaosAI login renewal failed to start: `{exc}`"
    oauth_url = str(payload.get("oauthUrl") or "").strip()
    status = str(payload.get("status") or "").strip() or "unknown"
    if not oauth_url:
        return f"KaosAI login renewal started, but no login URL is available yet. Status: `{status}`"
    return "\n".join(
        [
            "## KaosAI login renewal",
            "Open this URL, sign in, then paste the callback URL here.",
            oauth_url,
        ]
    )


def _render_kaosai_clarify_preview(plan: dict[str, Any]) -> str:
    parameters = plan.get("parameters")
    question = _preview_value(parameters.get("question")) if isinstance(parameters, dict) else ""
    lines = ["## KaosAI plan", "intent: clarify", "confirmation: not required"]
    if question:
        lines.append(f"- question: {question}")
    lines.append("- execution: skipped")
    return "\n".join(lines)


def _render_kaosai_rejected_preview(plan: dict[str, Any], reason: str) -> str:
    intent = _preview_value(plan.get("intent")) or "unknown"
    scope = _preview_value(plan.get("scope"))
    lines = ["## KaosAI rejected", f"reason: `{reason}`", f"intent: {intent}"]
    if scope:
        lines.append(f"scope: {scope}")
    lines.append("- execution: skipped")
    return "\n".join(lines)


def parse_document_tag_suggestion(text: str) -> str:
    lowered = text.casefold()
    if not any(marker in lowered for marker in ("tag", "tags", "태그")):
        return ""
    if not any(marker in lowered for marker in ("suggest", "recommend", "auto", "자동", "추천")):
        return ""
    for match in DOCUMENT_TAG_SUGGESTION_PATTERN.finditer(text):
        document_id = match.group(1)
        if int(document_id) > 0:
            return document_id
    return ""


def _render_kaosai_guard_preview(guarded: BrainGuardResult) -> str:
    confirmation = "required" if guarded.confirmation_required else "not required"
    lines = [
        "## KaosAI plan",
        f"intent: {guarded.intent}",
        f"kind: {guarded.kind.value}",
        f"confirmation: {confirmation}",
    ]
    lines.extend(_guarded_request_lines(guarded.request))
    lines.append("- execution: skipped")
    return "\n".join(lines)


def _guarded_request_lines(request: object) -> list[str]:
    if isinstance(request, ToolRequest):
        lines = [f"- tool: {request.kind.value}"]
        if request.query:
            lines.append(f"- query: {_preview_value(request.query)}")
        if request.start or request.end:
            lines.append(f"- window: {request.start or '..'} ~ {request.end or '..'}")
        if request.profile:
            lines.append(f"- profile: {request.profile}")
        return lines
    if isinstance(request, TaskCreateRequest):
        lines = [f"- title: {_preview_value(request.title)}"]
        if due := _preview_due(request.due_date, request.due_time):
            lines.append(f"- due: {due}")
        lines.append(f"- profile: {request.profile}")
        return lines
    if isinstance(request, TaskDueUpdateRequest):
        lines = [
            f"- task: {_preview_value(request.task_title)}",
            f"- due: {_preview_due(request.due_date, request.due_time)}",
            f"- profile: {request.profile}",
        ]
        return lines
    if isinstance(request, TaskActionRequest):
        return [
            f"- action: {request.action}",
            f"- task: {_preview_value(request.task_title)}",
            f"- profile: {request.profile}",
        ]
    if isinstance(request, GovernorTaskEditRequest):
        lines = [
            f"- task: {_preview_value(request.task_title)}",
            f"- title: {_preview_value(request.title)}",
        ]
        if request.memo:
            lines.append(f"- memo: {_preview_value(request.memo, limit=120)}")
        if due := _preview_due(request.due_date, request.due_time):
            lines.append(f"- due: {due}")
        if request.priority:
            lines.append(f"- priority: {_preview_value(request.priority)}")
        lines.append(f"- profile: {request.profile}")
        return lines
    if isinstance(request, EventCreateRequest):
        lines = [
            f"- title: {_preview_value(request.title)}",
            f"- date: {request.start_date}" if request.start_date == request.end_date else f"- date: {request.start_date} ~ {request.end_date}",
            f"- allDay: {str(request.all_day).lower()}",
            f"- profile: {request.profile}",
        ]
        if request.memo:
            lines.append(f"- memo: {_preview_value(request.memo, limit=120)}")
        return lines
    if isinstance(request, MemoCreateRequest):
        return [f"- content: {_preview_value(request.content, limit=160)}"]
    if isinstance(request, MemoEditRequest):
        return [
            f"- query: {_preview_value(request.query)}",
            f"- content: {_preview_value(request.content, limit=160)}",
        ]
    if isinstance(request, MemoDeleteRequest):
        return [f"- query: {_preview_value(request.query)}"]
    return ["- request: unknown"]


def _preview_due(due_date: str, due_time: str) -> str:
    return " ".join(part for part in (due_date, due_time) if part).strip()


def _preview_value(value: object, *, limit: int = 80) -> str:
    text = discord.utils.escape_mentions(" ".join(str(value or "").split()))
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


class BrainBot(discord.Client):
    def __init__(
        self,
        settings: Settings,
        ollama: OllamaClient | None = None,
        kaosai: KaosAIPlanner | None = None,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=NO_MENTIONS)
        self.settings = settings
        self.ollama = ollama or OllamaClient(
            OllamaConfig(
                base_url=settings.ollama_base_url,
                chat_model=settings.chat_model,
                deep_model=settings.deep_model,
                imaging_model=settings.imaging_model,
                timeout_seconds=settings.request_timeout_seconds,
            )
        )
        self.kaosai = kaosai or _kaosai_planner_from_settings(settings)
        self.reauth = (
            OpenClawReauthClient(
                ReauthConfig(
                    base_url=settings.kaosai_reauth_base_url,
                    api_token=settings.kaosai_reauth_api_token,
                    timeout_seconds=settings.kaosai_reauth_timeout_seconds,
                )
            )
            if settings.kaosai_reauth_enabled
            else None
        )
        self.governor_tools = (
            GovernorToolClient(
                GovernorToolConfig(
                    base_url=settings.governor_tools_base_url,
                    api_token=settings.governor_tools_api_token,
                    profile=settings.governor_tools_profile,
                    supplies_collection_id=settings.governor_tools_supplies_collection_id,
                    timeout_seconds=settings.governor_tools_timeout_seconds,
                )
            )
            if settings.governor_tools_enabled
            else None
        )
        self._active_control_message_id = 0
        self._active_control_refresh_task: asyncio.Task[None] | None = None

    async def on_ready(self) -> None:
        LOGGER.info("KaosBrain connected as %s", self.user)
        if self.governor_tools is not None and (
            self._active_control_refresh_task is None or self._active_control_refresh_task.done()
        ):
            self._active_control_refresh_task = asyncio.create_task(self._ensure_active_control_message())

    def _allowed(self, message: discord.Message) -> bool:
        return (
            message.guild is not None
            and message.guild.id == self.settings.guild_id
            and message.channel.id == self.settings.brain_channel_id
            and message.author.id in self.settings.allowed_user_ids
        )

    def _strip_mention(self, message: discord.Message) -> str:
        content = message.content.strip()
        if self.user is None:
            return content
        mention_forms = {f"<@{self.user.id}>", f"<@!{self.user.id}>"}
        for mention in mention_forms:
            content = content.replace(mention, "").strip()
        return content

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not self._allowed(message):
            return
        mentioned = self.user is not None and self.user in message.mentions
        if not self.settings.respond_without_mention and not mentioned:
            return
        text = self._strip_mention(message)
        if _is_openai_callback(text):
            await self._submit_kaosai_reauth_callback(message, text)
            return
        request = parse_request(text)
        if request is None:
            return
        if request.route is Route.CHAT and _is_kaosai_reauth_command(request.text):
            await self._start_kaosai_reauth(message)
            return
        if request.route is Route.CHAT and request.text.strip().lower().startswith("ai:"):
            await self._answer_with_kaosai_diagnostic(message, request.text)
            return
        if request.route is Route.CHAT and self.settings.kaosai_dry_run_enabled:
            async with message.channel.typing():
                reply = await self._render_kaosai_diagnostic(request.text, message=message)
            await message.reply(
                reply[: self.settings.max_reply_chars],
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        task_update = (
            parse_task_due_update(request.text, today=message.created_at.astimezone(KST).date())
            if request.route is Route.CHAT
            else None
        )
        if task_update is not None:
            await self._propose_task_due_update(message, task_update)
            return
        task_edit = parse_task_edit(request.text) if request.route is Route.CHAT else None
        if task_edit is not None:
            await self._propose_task_edit(message, task_edit)
            return
        task_create = (
            parse_task_create(request.text, today=message.created_at.astimezone(KST).date())
            if request.route is Route.CHAT
            else None
        )
        if task_create is not None:
            await self._propose_task_create(message, task_create)
            return
        task_action = parse_task_action(request.text) if request.route is Route.CHAT else None
        if task_action is not None:
            await self._propose_task_action(message, task_action)
            return
        event_create = (
            parse_event_create(request.text, today=message.created_at.astimezone(KST).date())
            if request.route is Route.CHAT
            else None
        )
        if event_create is not None:
            await self._propose_event_create(message, event_create)
            return
        memo_edit = parse_memo_edit(request.text) if request.route is Route.CHAT else None
        if memo_edit is not None:
            await self._propose_memo_edit(message, memo_edit)
            return
        memo_delete = parse_memo_delete(request.text) if request.route is Route.CHAT else None
        if memo_delete is not None:
            await self._propose_memo_delete(message, memo_delete)
            return
        memo_create = parse_memo_create(request.text) if request.route is Route.CHAT else None
        if memo_create is not None:
            await self._propose_memo_create(message, memo_create)
            return
        document_tag_suggestion = parse_document_tag_suggestion(request.text) if request.route is Route.CHAT else ""
        if document_tag_suggestion:
            await self._propose_document_tag_suggestion(message, document_tag_suggestion)
            return
        view: discord.ui.View | None = None
        async with message.channel.typing():
            try:
                if request.route is Route.CHAT and self.settings.kaosai_chat_enabled:
                    kaosai_reply = await self._answer_with_kaosai_plan(request.text, message=message)
                    if kaosai_reply is not None:
                        reply, view = kaosai_reply
                        sent = await message.reply(
                            reply[: self.settings.max_reply_chars],
                            view=view,
                            mention_author=False,
                            allowed_mentions=NO_MENTIONS,
                        )
                        _bind_view_message(view, sent)
                        return
                tool_request = (
                    parse_tool_request(request.text, today=message.created_at.astimezone(KST).date())
                    if request.route is Route.CHAT
                    else None
                )
                if tool_request is not None:
                    reply, view = await self._answer_with_governor_tool(request.text, tool_request, actor_id=int(message.author.id))
                elif request.route is Route.CHAT and self.settings.auto_route_enabled:
                    reply = await self.ollama.generate_auto(request.text)
                else:
                    reply = await self.ollama.generate(request.route, request.text)
            except OllamaError as exc:
                LOGGER.warning("Ollama failed route=%s: %s", request.route.value, exc)
                label = "Deep thinking failed" if request.route is Route.DEEP else "Brain failed"
                reply = f"{label}: {exc}"
        sent = await message.reply(
            reply[: self.settings.max_reply_chars],
            view=view,
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )
        _bind_view_message(view, sent)

    async def _answer_with_kaosai_plan(
        self,
        user_text: str,
        *,
        message: discord.Message,
    ) -> tuple[str, discord.ui.View | None] | None:
        try:
            plan = await self.kaosai.plan(
                user_text,
                context={
                    "actorId": str(message.author.id),
                    "channelId": str(message.channel.id),
                    "today": message.created_at.astimezone(KST).date().isoformat(),
                },
            )
        except KaosAIError as exc:
            LOGGER.warning("KaosAI planner failed: %s", exc)
            if self.reauth is not None and _looks_like_auth_failure(str(exc)):
                return ("## KaosAI login expired\nRenew ChatGPT login.", KaosAIReauthView(self.reauth, int(message.author.id)))
            return None
        if plan is None:
            return None
        if str(plan.get("intent") or "").strip() == "clarify":
            parameters = plan.get("parameters")
            question = str(parameters.get("question") or "").strip() if isinstance(parameters, dict) else ""
            return (question or "조금 더 자세히 말해줘요.", None)
        try:
            guarded = adapt_kaosai_plan(
                plan,
                BrainGuardContext(
                    actor_id=int(message.author.id),
                    idempotency_key=f"discord:{message.id}",
                    today=message.created_at.astimezone(KST).date(),
                    default_profile=self.settings.governor_tools_profile,
                    supplies_collection_id=self.settings.governor_tools_supplies_collection_id,
                ),
            )
        except BrainGuardError as exc:
            LOGGER.warning("KaosAI plan rejected by Brain Guard: %s", exc)
            return None
        return await self._answer_with_guarded_plan(user_text, guarded)

    async def _answer_with_kaosai_diagnostic(self, message: discord.Message, text: str) -> None:
        command = text.strip()
        lower_command = command.lower()
        if lower_command == "ai:ping":
            user_text = "ping"
        elif lower_command.startswith("ai:plan "):
            user_text = command[len("ai:plan ") :].strip()
            if not user_text:
                await message.reply(
                    "사용법: `ai:plan 할 말`",
                    mention_author=False,
                    allowed_mentions=NO_MENTIONS,
                )
                return
        else:
            await message.reply(
                "사용법: `ai:ping` 또는 `ai:plan 할 말`",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        async with message.channel.typing():
            reply = await self._render_kaosai_diagnostic(user_text, message=message)
        await message.reply(
            reply[: self.settings.max_reply_chars],
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _start_kaosai_reauth(self, message: discord.Message) -> None:
        if self.reauth is None:
            await message.reply(
                "KaosAI reauth agent is not enabled.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        async with message.channel.typing():
            content = await _start_reauth_message(self.reauth)
        await message.reply(content[: self.settings.max_reply_chars], mention_author=False, allowed_mentions=NO_MENTIONS)

    async def _submit_kaosai_reauth_callback(self, message: discord.Message, callback: str) -> None:
        if self.reauth is None:
            return
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.warning("Failed to delete OpenAI callback message")
        async with message.channel.typing():
            try:
                payload = await self.reauth.submit_callback(callback)
            except ReauthError as exc:
                reply = f"KaosAI login renewal failed: `{exc}`"
            else:
                status = str(payload.get("status") or "")
                if status == "succeeded":
                    reply = "KaosAI login renewed."
                else:
                    reply = f"KaosAI login renewal status: `{status or 'unknown'}`"
        await message.channel.send(reply[: self.settings.max_reply_chars], allowed_mentions=NO_MENTIONS)

    async def _render_kaosai_diagnostic(self, user_text: str, *, message: discord.Message) -> str:
        try:
            plan = await self.kaosai.plan(
                user_text,
                context={
                    "actorId": str(message.author.id),
                    "channelId": str(message.channel.id),
                    "today": message.created_at.astimezone(KST).date().isoformat(),
                },
            )
        except KaosAIError as exc:
            return f"## KaosAI diagnostic\n- planner: failed `{exc}`"
        if plan is None:
            return "## KaosAI diagnostic\n- planner: unavailable"
        if str(plan.get("intent") or "").strip() == "clarify":
            return _render_kaosai_clarify_preview(plan)
        try:
            guarded = adapt_kaosai_plan(
                plan,
                BrainGuardContext(
                    actor_id=int(message.author.id),
                    idempotency_key=f"discord-diagnostic:{message.id}",
                    today=message.created_at.astimezone(KST).date(),
                    default_profile=self.settings.governor_tools_profile,
                    supplies_collection_id=self.settings.governor_tools_supplies_collection_id,
                ),
            )
        except BrainGuardError as exc:
            return _render_kaosai_rejected_preview(plan, str(exc))
        return _render_kaosai_guard_preview(guarded)

    async def _answer_with_guarded_plan(
        self,
        user_text: str,
        guarded: BrainGuardResult,
    ) -> tuple[str, discord.ui.View | None]:
        if guarded.kind is BrainGuardResultKind.READONLY_TOOL:
            return await self._answer_with_governor_tool(user_text, guarded.request, actor_id=guarded.actor_id)  # type: ignore[arg-type]
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

    async def _answer_with_governor_tool(
        self,
        user_text: str,
        tool_request: ToolRequest,
        *,
        actor_id: int,
    ) -> tuple[str, discord.ui.View | None]:
        if self.governor_tools is None:
            return _tool_unavailable(), None
        if tool_request.kind is ToolKind.SEARCH_ALL:
            try:
                memo_payload, document_payload = await asyncio.gather(
                    self.governor_tools.fetch(ToolRequest(ToolKind.MEMO_SEARCH, tool_request.query)),
                    self.governor_tools.fetch(ToolRequest(ToolKind.DOCUMENT_SEARCH, tool_request.query)),
                )
            except GovernorToolError as exc:
                LOGGER.warning("Governor combined search failed: %s", exc)
                return _tool_failed("조회"), None
            document_results = [
                {
                    **item,
                    "url": item.get("url") or item.get("publicUrl") or document_public_url(self.settings.paperless_public_url, item.get("id")),
                }
                for item in search_results(document_payload)
            ]
            document_payload = {**document_payload, "results": document_results}
            memo_results = search_results(memo_payload)
            view = (
                BrainMemoSearchView(
                    self.governor_tools,
                    actor_id,
                    tool_request.query,
                    memo_results,
                    memos_public_url=self.settings.memos_public_url,
                )
                if len(memo_results) > 1
                else BrainTemporarySearchView(tool_request.query)
            )
            return render_combined_search_context(tool_request.query, memo_payload, document_payload), view
        try:
            payload = await self.governor_tools.fetch(tool_request)
        except GovernorToolError as exc:
            LOGGER.warning("Governor tool failed kind=%s: %s", tool_request.kind.value, exc)
            return _tool_failed("조회"), None
        if tool_request.kind is ToolKind.MEMO_SEARCH:
            context = render_tool_context(tool_request, payload)
            results = search_results(payload)
            if len(results) == 1:
                item = results[0]
                content = render_memo_opened(tool_request.query, item)
                view = BrainOpenedMemoView(self.governor_tools, actor_id, str(item.get("name") or ""), content)
                return content, view
            view = (
                BrainMemoSearchView(
                    self.governor_tools,
                    actor_id,
                    tool_request.query,
                    results,
                    memos_public_url=self.settings.memos_public_url,
                )
                if len(results) > 1
                else None
            )
            return context, view
        if tool_request.kind is ToolKind.DOCUMENT_SEARCH:
            results = search_results(payload)
            linked_results = [
                {
                    **item,
                    "url": item.get("url") or item.get("publicUrl") or document_public_url(self.settings.paperless_public_url, item.get("id")),
                }
                for item in results
            ]
            payload = {**payload, "results": linked_results}
            context = render_tool_context(tool_request, payload)
            view = BrainTemporarySearchView(tool_request.query) if linked_results else None
            return context, view
        context = render_tool_context(tool_request, payload)
        if tool_request.kind is ToolKind.COMPLETED_TASKS:
            tasks = _task_results(payload)
            view = BrainCompletedTasksView(self.governor_tools, actor_id, tool_request, tasks) if tasks else None
            return context, view
        if tool_request.kind is ToolKind.ACTIVE_TASKS:
            tasks = _task_results(payload)
            view = BrainActiveTasksView(self.governor_tools, actor_id, tool_request, tasks) if tasks else None
            return context, view
        if tool_request.kind is ToolKind.TODAY:
            return context, None
        try:
            return await self.ollama.summarize_tool_result(user_text, context), None
        except OllamaError:
            return context, None

    async def _ensure_active_control_message(self) -> None:
        if self.governor_tools is None or self.user is None:
            return
        try:
            channel = self.get_channel(self.settings.brain_channel_id) or await self.fetch_channel(self.settings.brain_channel_id)
            if not isinstance(channel, discord.TextChannel | discord.Thread):
                return
            tasks, supplies = await self._active_control_items()
            content = render_active_control_message(tasks, supplies)
            view = BrainActiveControlView(self.governor_tools, self.settings, tasks, supplies)
            message = await self._find_active_control_message(channel)
            if message is None:
                message = await channel.send(content=content, view=view, allowed_mentions=NO_MENTIONS)
            else:
                await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
            self._active_control_message_id = int(message.id)
        except Exception as exc:
            LOGGER.warning("Active control message refresh failed: %s", exc)

    async def _find_active_control_message(self, channel: discord.TextChannel | discord.Thread) -> discord.Message | None:
        if self._active_control_message_id:
            try:
                return await channel.fetch_message(self._active_control_message_id)
            except discord.HTTPException:
                self._active_control_message_id = 0
        async for message in channel.history(limit=50):
            if message.author.id == self.user.id and str(message.content or "").startswith(ACTIVE_CONTROL_MARKER):
                return message
        return None

    async def _active_control_items(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self.governor_tools is None:
            return [], []
        tasks_payload = await self.governor_tools.fetch(ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile))
        supplies_payload = await self.governor_tools.fetch(
            ToolRequest(
                ToolKind.ACTIVE_TASKS,
                profile="supplies",
                collection_id=self.settings.governor_tools_supplies_collection_id,
            )
        )
        return _task_results(tasks_payload), _task_results(supplies_payload)

    async def _propose_task_due_update(self, message: discord.Message, request: TaskDueUpdateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_task_due_update(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task due edit proposal failed: %s", exc)
            await message.reply(
                _tool_failed("할 일 수정"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_task_due_update_proposal(payload),
            view=TaskUpdateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_task_create(self, message: discord.Message, request: TaskCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_task_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task creation proposal failed: %s", exc)
            await message.reply(
                _tool_failed("할 일 저장"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_task_create_proposal(payload),
            view=TaskCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_task_action(self, message: discord.Message, request: TaskActionRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_task_action(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Task action proposal failed: %s", exc)
            await message.reply(
                _tool_failed("할 일 변경"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_task_action_proposal(payload),
            view=TaskActionConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_task_edit(self, message: discord.Message, request: TaskTextEditRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
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
            await message.reply(
                _tool_failed("할 일 수정"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_task_edit_proposal(payload),
            view=TaskEditConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_event_create(self, message: discord.Message, request: EventCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_event_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Event creation proposal failed: %s", exc)
            await message.reply(
                _tool_failed("일정 저장"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_event_create_proposal(payload),
            view=EventCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_memo_create(self, message: discord.Message, request: MemoCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_memo_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Memo creation proposal failed: %s", exc)
            await message.reply(
                _tool_failed("메모 저장"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_memo_create_proposal(payload),
            view=MemoCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_memo_delete(self, message: discord.Message, request: MemoDeleteRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_memo_delete(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Memo delete proposal failed: %s", exc)
            await message.reply(
                _tool_failed("메모 삭제"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_memo_delete_proposal(payload),
            view=MemoDeleteConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_memo_edit(self, message: discord.Message, request: MemoEditRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                _tool_unavailable(),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_memo_edit(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            LOGGER.warning("Memo edit proposal failed: %s", exc)
            await message.reply(
                _tool_failed("메모 수정"),
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_memo_edit_proposal(payload),
            view=MemoEditConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )


class BrainTemporarySearchView(discord.ui.View):
    def __init__(self, search_title: str) -> None:
        super().__init__(timeout=BRAIN_SEARCH_WINDOW_SECONDS)
        self.search_title = search_title.strip() or "search"
        self._message: discord.Message | None = None

    def bind_message(self, message: discord.Message) -> None:
        self._message = message

    async def delete_message(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete Brain search window %s", getattr(self._message, "id", ""))
        finally:
            self._message = None

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.edit(
                content=f"Search result of {self.search_title} expired after 10 mins.",
                view=None,
                allowed_mentions=NO_MENTIONS,
            )
        except discord.HTTPException:
            LOGGER.info("Could not expire Brain search window %s", getattr(self._message, "id", ""))
        finally:
            self._message = None


class KaosAIReauthView(discord.ui.View):
    def __init__(self, reauth: OpenClawReauthClient, actor_id: int) -> None:
        super().__init__(timeout=600)
        self.reauth = reauth
        self.actor_id = actor_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.actor_id:
            await interaction.response.send_message("이 버튼은 요청한 사용자만 사용할 수 있어요.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Renew ChatGPT Login", style=discord.ButtonStyle.primary)
    async def renew(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        content = await _start_reauth_message(self.reauth)
        await interaction.edit_original_response(content=content, view=None, allowed_mentions=NO_MENTIONS)


class BrainMemoSearchView(BrainTemporarySearchView):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        query: str,
        results: list[dict[str, Any]],
        *,
        memos_public_url: str = "",
    ) -> None:
        super().__init__(query)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.results = results[:25]
        self.memos_public_url = memos_public_url
        self.add_item(BrainMemoSearchSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainMemoSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainMemoSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=memo_option_label(item),
                description=memo_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.results)
        ]
        super().__init__(placeholder="Open memo", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_memo(str(item.get("name") or ""))
            memo = payload.get("memo")
            if isinstance(memo, dict):
                item = {**item, **memo, "full": True}
            content = render_memo_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Memo open failed: %s", exc)
            content = _tool_failed("메모 열기")
            await interaction.response.send_message(content, ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        view = BrainOpenedMemoView(self.parent_view.governor_tools, self.parent_view.actor_id, str(item.get("name") or ""), content)
        await interaction.response.defer()
        await interaction.followup.send(content, view=view, allowed_mentions=NO_MENTIONS)
        await self.parent_view.delete_message()
        self.parent_view.stop()


class BrainOpenedMemoView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.message.delete()

    @discord.ui.button(label="More...", style=discord.ButtonStyle.secondary)
    async def more(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoActionsView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainOpenedMemoActionsView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.message.delete()

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainMemoEditConfirmView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainMemoDeleteConfirmView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainMemoEditConfirmView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Edit Memo", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            BrainMemoEditModal(self.governor_tools, self.actor_id, self.name, self.content, interaction.message)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainMemoEditModal(discord.ui.Modal, title="Edit memo"):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        name: str,
        content: str,
        source_message: discord.Message | None,
    ) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.source_message = source_message
        self.content_input = discord.ui.TextInput(
            label="Memo",
            style=discord.TextStyle.paragraph,
            default=content[:4000],
            max_length=4000,
            required=True,
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        content = str(self.content_input.value).strip()
        await interaction.response.defer(ephemeral=True)
        try:
            proposal = await self.governor_tools.propose_memo_edit_by_name(
                self.name,
                content,
                actor_id=self.actor_id,
                idempotency_key=f"brain-memo-edit-{interaction.id}",
            )
            payload = await self.governor_tools.approve_confirmation(
                str(proposal.get("confirmationId") or ""),
                actor_id=self.actor_id,
            )
            memo = payload.get("memo")
            if isinstance(memo, dict):
                content = str(memo.get("content") or content)
        except GovernorToolError as exc:
            LOGGER.warning("Memo edit failed: %s", exc)
            await interaction.followup.send(_tool_failed("메모 수정"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if self.source_message is not None:
            view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, content)
            await self.source_message.edit(content=content[:1900], view=view, allowed_mentions=NO_MENTIONS)
            return
        await interaction.followup.send(
            content[:1900],
            view=BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, content),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )


class BrainMemoDeleteConfirmView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Delete Memo", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            proposal = await self.governor_tools.propose_memo_delete_by_name(
                self.name,
                actor_id=self.actor_id,
                idempotency_key=f"brain-memo-delete-{interaction.id}",
            )
            await self.governor_tools.approve_confirmation(str(proposal.get("confirmationId") or ""), actor_id=self.actor_id)
        except GovernorToolError as exc:
            LOGGER.warning("Memo delete failed: %s", exc)
            await _edit_deferred_component(interaction, content=_tool_failed("메모 삭제"), view=self)
            return
        deleted_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        view = BrainDeletedMemoView(self.governor_tools, self.actor_id, self.content)
        await _edit_deferred_component(interaction, content=render_memo_deleted(self.content, deleted_at), view=view)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainDeletedMemoView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Undo Delete", style=discord.ButtonStyle.primary)
    async def undo(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            proposal = await self.governor_tools.propose_memo_create(
                MemoCreateRequest(self.content),
                actor_id=self.actor_id,
                idempotency_key=f"brain-memo-undo-delete-{interaction.id}",
            )
            payload = await self.governor_tools.approve_confirmation(
                str(proposal.get("confirmationId") or ""),
                actor_id=self.actor_id,
            )
            memo = payload.get("memo")
            name = str(memo.get("name") or "") if isinstance(memo, dict) else ""
            content = str(memo.get("content") or self.content) if isinstance(memo, dict) else self.content
        except GovernorToolError as exc:
            LOGGER.warning("Memo restore failed: %s", exc)
            await _edit_deferred_component(interaction, content=_tool_failed("메모 복구"), view=self)
            return
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, name, content)
        await _edit_deferred_component(interaction, content=content[:1900], view=view)
        self.stop()

    @discord.ui.button(label="Delete this Message", style=discord.ButtonStyle.danger)
    async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message(_tool_failed("메시지 삭제"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.message.delete()


class BrainDocumentSearchView(BrainTemporarySearchView):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        query: str,
        results: list[dict[str, Any]],
        *,
        paperless_public_url: str = "",
    ) -> None:
        super().__init__(query)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.results = results[:25]
        self.paperless_public_url = paperless_public_url
        self.add_item(BrainDocumentSearchSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainDocumentSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainDocumentSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=document_option_label(item),
                description=document_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.results)
        ]
        super().__init__(placeholder="Open document", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_document(item.get("id"))
            document = payload.get("document")
            if isinstance(document, dict):
                item = {**item, **document, "full": True}
            content = render_document_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Document open failed: %s", exc)
            content = _tool_failed("문서 열기")
        await interaction.response.defer()
        await interaction.followup.send(
            content,
            view=BrainOpenedDocumentView(
                self.parent_view.actor_id,
                document_public_url(self.parent_view.paperless_public_url, item.get("id")),
            ),
            allowed_mentions=NO_MENTIONS,
        )
        await self.parent_view.delete_message()
        self.parent_view.stop()


class BrainOpenedDocumentView(discord.ui.View):
    def __init__(self, actor_id: int, url: str = "") -> None:
        super().__init__(timeout=600)
        self.actor_id = actor_id
        if url:
            self.add_item(discord.ui.Button(label="Open document", style=discord.ButtonStyle.link, url=url))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.message.delete()


class BrainCompletedTasksView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, tasks: list[dict[str, Any]]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.tasks = tasks[:25]
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
        await interaction.followup.send(
            render_task_action_proposal(payload),
            view=TaskActionConfirmationView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                str(payload.get("confirmationId") or ""),
            ),
            allowed_mentions=NO_MENTIONS,
        )


def render_active_control_message(tasks: list[dict[str, Any]], supplies: list[dict[str, Any]]) -> str:
    lines = [
        ACTIVE_CONTROL_MARKER,
        f"- Tasks: {len(tasks)} active",
        f"- Supplies: {len(supplies)} active",
    ]
    if len(tasks) > ACTIVE_CONTROL_LIMIT:
        lines.append(f"- Tasks dropdown shows first {ACTIVE_CONTROL_LIMIT}.")
    if len(supplies) > ACTIVE_CONTROL_LIMIT:
        lines.append(f"- Supplies dropdown shows first {ACTIVE_CONTROL_LIMIT}.")
    return "\n".join(lines)


class BrainActiveControlView(discord.ui.View):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        settings: Settings,
        tasks: list[dict[str, Any]],
        supplies: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.settings = settings
        self.tasks = tasks[:ACTIVE_CONTROL_LIMIT]
        self.supplies = supplies[:ACTIVE_CONTROL_LIMIT]
        if self.tasks:
            self.add_item(BrainActiveControlSelect(self, "tasks", self.tasks))
        if self.supplies:
            self.add_item(BrainActiveControlSelect(self, "supplies", self.supplies))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == self.settings.guild_id
            and interaction.channel_id == self.settings.brain_channel_id
            and int(interaction.user.id) in self.settings.allowed_user_ids
        ):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def request_for_kind(self, kind: str) -> ToolRequest:
        if kind == "supplies":
            return ToolRequest(
                ToolKind.ACTIVE_TASKS,
                profile="supplies",
                collection_id=self.settings.governor_tools_supplies_collection_id,
            )
        return ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile)

    async def refresh_items(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tasks_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile)
        )
        supplies_payload = await self.governor_tools.fetch(
            ToolRequest(
                ToolKind.ACTIVE_TASKS,
                profile="supplies",
                collection_id=self.settings.governor_tools_supplies_collection_id,
            )
        )
        return _task_results(tasks_payload), _task_results(supplies_payload)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            tasks, supplies = await self.refresh_items()
        except GovernorToolError as exc:
            LOGGER.warning("Active control refresh failed: %s", exc)
            await interaction.followup.send(_tool_failed("Active 갱신"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.edit_original_response(
            content=render_active_control_message(tasks, supplies),
            view=BrainActiveControlView(self.governor_tools, self.settings, tasks, supplies),
            allowed_mentions=NO_MENTIONS,
        )


class BrainActiveControlSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveControlView, kind: str, tasks: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.kind = kind
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(task) or None,
                value=str(index),
            )
            for index, task in enumerate(tasks[:ACTIVE_CONTROL_LIMIT])
        ]
        placeholder = "Active supplies" if kind == "supplies" else "Active tasks"
        row = 1 if kind == "supplies" else 0
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            items = self.parent_view.supplies if self.kind == "supplies" else self.parent_view.tasks
            task = items[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Active control selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("항목 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.followup.send(
            _render_active_task_selection(title, task, supplies=self.kind == "supplies"),
            view=BrainActiveTaskActionsView(
                self.parent_view.governor_tools,
                int(interaction.user.id),
                self.parent_view.request_for_kind(self.kind),
                task,
            ),
            allowed_mentions=NO_MENTIONS,
        )


class BrainActiveTasksView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, tasks: list[dict[str, Any]]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.tasks = tasks[:25]
        self.add_item(BrainActiveTasksSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainActiveTasksSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveTasksView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(task) or None,
                value=str(index),
            )
            for index, task in enumerate(parent.tasks)
        ]
        super().__init__(placeholder="Choose active item", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            task = self.parent_view.tasks[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Task selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("할 일 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.followup.send(
            f"## {title}",
            view=BrainActiveTaskActionsView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                self.parent_view.request,
                task,
            ),
            allowed_mentions=NO_MENTIONS,
        )


class BrainActiveTaskActionsView(discord.ui.View):
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
        await interaction.message.delete()

    async def _propose(self, interaction: discord.Interaction, action: str) -> None:
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
            await interaction.response.send_message(_tool_failed("할 일 변경"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.edit_message(
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


class TaskEditConfirmationView(discord.ui.View):
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


class TaskUpdateConfirmationView(discord.ui.View):
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


class TaskCreateConfirmationView(discord.ui.View):
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


class EventCreateConfirmationView(discord.ui.View):
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
            content = render_event_create_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Event creation approval failed: %s", exc)
            content = _tool_failed("일정 저장")
        for item in self.children:
            item.disabled = True
        await _edit_deferred_component(interaction, content=content, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("일정 저장"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class TaskActionConfirmationView(discord.ui.View):
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
        for item in self.children:
            item.disabled = True
        await _edit_deferred_component(interaction, content=content, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("할 일 변경"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class MemoCreateConfirmationView(discord.ui.View):
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
            content = render_memo_create_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Memo creation approval failed: %s", exc)
            content = _tool_failed("메모 저장")
        for item in self.children:
            item.disabled = True
        await _edit_deferred_component(interaction, content=content, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("메모 저장"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class MemoDeleteConfirmationView(discord.ui.View):
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

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_memo_delete_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Memo delete approval failed: %s", exc)
            content = _tool_failed("메모 삭제")
        for item in self.children:
            item.disabled = True
        await _edit_deferred_component(interaction, content=content, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("메모 삭제"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class MemoEditConfirmationView(discord.ui.View):
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
            content = render_memo_edit_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Memo edit approval failed: %s", exc)
            content = _tool_failed("메모 수정")
        for item in self.children:
            item.disabled = True
        await _edit_deferred_component(interaction, content=content, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=_tool_cancelled("메모 수정"), view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class DocumentTagConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.actor_id:
            await interaction.response.send_message("Only the requester can confirm this document tag change.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_document_tags_completed(payload)
        except GovernorToolError as exc:
            LOGGER.warning("Document tag confirmation failed: %s", exc)
            content = _tool_failed("문서 태그 수정")
        await _edit_deferred_component(interaction, content=content, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="문서 태그 수정 취소했어요.", view=None, allowed_mentions=NO_MENTIONS)
        self.stop()


def _task_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tasks")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _uses_supplies_request(request: ToolRequest) -> bool:
    return request.profile == "supplies" or "supplies" in request.collection_id.lower()


def _render_active_task_selection(title: str, task: dict[str, Any], *, supplies: bool) -> str:
    lines = [f"## {title}"]
    if not supplies:
        due = " ".join(
            part
            for part in (
                str(task.get("due") or task.get("dueDate") or "").strip(),
                str(task.get("dueTime") or "").strip(),
            )
            if part
        )
        if due:
            lines.append(f"- due: {due}")
    return "\n".join(lines)


def _task_option_label(task: dict[str, Any]) -> str:
    return _compact_select_text(str(task.get("title") or task.get("summary") or "Untitled task"), 100)


def _task_option_description(task: dict[str, Any]) -> str:
    completed = str(task.get("completedDate") or task.get("completed") or task.get("completedAt") or "").strip()[:10]
    due = str(task.get("due") or task.get("dueDate") or "").strip()
    parts = [part for part in (completed, due) if part]
    return _compact_select_text(" · ".join(parts), 100)


def _compact_select_text(value: str, limit: int) -> str:
    text = " ".join(value.split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
