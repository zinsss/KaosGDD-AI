from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import date, datetime, timedelta
import io
import json
import logging
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import discord

from .brain_guard import BrainGuardContext, BrainGuardError, BrainGuardResult, BrainGuardResultKind, adapt_kaosai_plan
from .config import Settings
from .event_intent import EventCreateRequest, parse_event_create
from .governor_tools import (
    DocumentTagRequest,
    FAMILY_EVENT_MARKER,
    FAMILY_EVENT_SUFFIX,
    GovernorToolClient,
    GovernorToolConfig,
    GovernorToolError,
    PERSONAL_EVENT_MARKER,
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
ACTIVE_CONTROL_MARKER = "# "
SERVICE_MENU_MARKER = "\u200b"
ACTIVE_CONTROL_LIMIT = 25
ACTIVE_CONTROL_HISTORY_LIMIT = 20
TASK_SERVICE_PAGE_SIZE = 25
TASK_SERVICE_HISTORY_LIMIT = 250
TASKS_SERVICE_BUTTON_LABEL = "Tasks"
ACTIVE_TASKS_LABEL = "Active Tasks"
CALENDAR_LABEL = "Calendar"
SUPPLIES_LABEL = "Supplies"
UPCOMING_EVENTS_LABEL = "Upcoming Events"
PAPERLESS_LABEL = "Paperless"
MEMOS_LABEL = "Memos"
FAX_MAIL_LABEL = "Fax Mail"
ACTIVE_TASKS_TITLE = "𝓐𝓬𝓽𝓲𝓿𝓮 𝓣𝓪𝓼𝓴𝓼"
TASKS_HISTORY_TITLE = "𝓣𝓪𝓼𝓴𝓼 𝓗𝓲𝓼𝓽𝓸𝓻𝔂"
CALENDAR_TITLE = "𝓒𝓪𝓵𝓮𝓷𝓭𝓪𝓻"
SUPPLIES_TITLE = "𝓢𝓾𝓹𝓹𝓵𝓲𝓮𝓼"
SUPPLIES_HISTORY_TITLE = "𝓢𝓾𝓹𝓹𝓵𝓲𝓮𝓼 𝓗𝓲𝓼𝓽𝓸𝓻𝔂"
PAPERLESS_TITLE = "𝓟𝓪𝓹𝓮𝓻𝓵𝓮𝓼𝓼"
MEMOS_TITLE = "𝓜𝓮𝓶𝓸𝓼"
KOREAN_SHORT_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


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


def _read_active_control_message_id(path: str) -> int:
    return _read_active_control_state_value(path, "messageId")


def _read_active_control_service_message_id(path: str) -> int:
    return _read_active_control_state_value(path, "serviceMessageId")


def _read_active_control_state_value(path: str, key: str) -> int:
    if not path:
        return 0
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    try:
        message_id = int(payload.get(key, 0))
    except (TypeError, ValueError):
        return 0
    return message_id if message_id > 0 else 0


def _write_active_control_message_id(path: str, message_id: int, service_message_id: int = 0) -> None:
    if not path or (message_id <= 0 and service_message_id <= 0):
        return
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, int] = {}
    try:
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload.update({key: int(value) for key, value in existing.items() if key in {"messageId", "serviceMessageId"}})
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        payload = {}
    if message_id > 0:
        payload["messageId"] = message_id
    if service_message_id > 0:
        payload["serviceMessageId"] = service_message_id
    tmp_path = state_path.with_suffix(f"{state_path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp_path.replace(state_path)


def _tool_cancelled(action: str) -> str:
    return f"{action} 취소했어요."


def _payload_count(payload: dict[str, Any], *keys: str, fallback: int) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return fallback


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
        self._active_control_message_id = _read_active_control_message_id(settings.active_control_state_path)
        self._active_control_service_message_id = _read_active_control_service_message_id(settings.active_control_state_path)
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
            memo_results = search_results(memo_payload)
            view = (
                BrainCombinedSearchView(
                    self.governor_tools,
                    actor_id,
                    tool_request.query,
                    memo_results,
                    document_results,
                    memo_count=_payload_count(memo_payload, "resultCount", "count", fallback=len(memo_results)),
                    memo_total=_payload_count(memo_payload, "totalCount", fallback=len(memo_results)),
                    document_count=_payload_count(document_payload, "resultCount", "count", fallback=len(document_results)),
                    document_total=_payload_count(document_payload, "totalCount", "total", fallback=len(document_results)),
                    paperless_public_url=self.settings.paperless_public_url,
                    memos_public_url=self.settings.memos_public_url,
                )
                if memo_results or document_results
                else None
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
            events, tasks, supplies, imports = await self._active_control_items()
            month_file = await self._active_control_month_file()
            content = render_active_control_message(events, tasks, supplies)
            view = BrainActiveControlView(self.governor_tools, self.settings, events, tasks, supplies, imports)
            message = await self._find_active_control_message(channel)
            if message is None:
                kwargs: dict[str, Any] = {"content": content, "view": view, "allowed_mentions": NO_MENTIONS}
                if month_file is not None:
                    kwargs["file"] = month_file
                message = await channel.send(**kwargs)
            else:
                kwargs = {"content": content, "view": view, "allowed_mentions": NO_MENTIONS}
                if month_file is not None:
                    kwargs["attachments"] = [month_file]
                await message.edit(**kwargs)
            self._active_control_message_id = int(message.id)
            service_message = await self._find_active_control_service_message(channel)
            service_view = BrainServiceMenuView(self.governor_tools, self.settings)
            if service_message is None:
                service_message = await channel.send(SERVICE_MENU_MARKER, view=service_view, allowed_mentions=NO_MENTIONS)
            else:
                await service_message.edit(content=SERVICE_MENU_MARKER, view=service_view, allowed_mentions=NO_MENTIONS)
            self._active_control_service_message_id = int(service_message.id)
            try:
                _write_active_control_message_id(
                    self.settings.active_control_state_path,
                    self._active_control_message_id,
                    self._active_control_service_message_id,
                )
            except OSError as exc:
                LOGGER.warning("Active control message state write failed: %s", exc)
        except Exception as exc:
            LOGGER.warning("Active control message refresh failed: %s", exc)

    async def _find_active_control_message(self, channel: discord.TextChannel | discord.Thread) -> discord.Message | None:
        if self._active_control_message_id:
            try:
                return await channel.fetch_message(self._active_control_message_id)
            except discord.HTTPException:
                self._active_control_message_id = 0
        async for message in channel.history(limit=ACTIVE_CONTROL_HISTORY_LIMIT):
            content = str(message.content or "")
            if (
                message.author.id == self.user.id
                and content.startswith(ACTIVE_CONTROL_MARKER)
            ):
                return message
        return None

    async def _find_active_control_service_message(self, channel: discord.TextChannel | discord.Thread) -> discord.Message | None:
        if self._active_control_service_message_id:
            try:
                return await channel.fetch_message(self._active_control_service_message_id)
            except discord.HTTPException:
                self._active_control_service_message_id = 0
        async for message in channel.history(limit=ACTIVE_CONTROL_HISTORY_LIMIT):
            content = str(message.content or "")
            if message.author.id == self.user.id and content == SERVICE_MENU_MARKER:
                return message
        return None

    async def _active_control_items(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if self.governor_tools is None:
            return [], [], [], []
        events_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.UPCOMING_EVENTS, profile=self.settings.governor_tools_profile)
        )
        tasks_payload = await self.governor_tools.fetch(ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile))
        supplies_payload = await self.governor_tools.fetch(
            ToolRequest(
                ToolKind.ACTIVE_TASKS,
                profile="supplies",
                collection_id=self.settings.governor_tools_supplies_collection_id,
            )
        )
        imports_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.RECENT_IMPORTS, profile=self.settings.governor_tools_profile)
        )
        return _event_results(events_payload), _task_results(tasks_payload), _task_results(supplies_payload), _import_results(imports_payload)

    async def _active_control_month_file(self) -> discord.File | None:
        return await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
        )

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
        super().__init__(placeholder=f"Memos: {len(parent.results)}", min_values=1, max_values=1, options=options)

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


class BrainCombinedSearchView(BrainTemporarySearchView):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        query: str,
        memo_results: list[dict[str, Any]],
        document_results: list[dict[str, Any]],
        *,
        memo_count: int = 0,
        memo_total: int = 0,
        document_count: int = 0,
        document_total: int = 0,
        paperless_public_url: str = "",
        memos_public_url: str = "",
    ) -> None:
        super().__init__(query)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.memo_results = memo_results[:25]
        self.document_results = document_results[:25]
        self.memo_count = memo_count or len(memo_results)
        self.memo_total = memo_total or self.memo_count
        self.document_count = document_count or len(document_results)
        self.document_total = document_total or self.document_count
        self.paperless_public_url = paperless_public_url
        self.memos_public_url = memos_public_url
        if self.memo_results:
            self.add_item(BrainCombinedMemoSearchSelect(self))
        if self.document_results:
            self.add_item(BrainCombinedDocumentSearchSelect(self))
        if self.document_results:
            self.add_item(BrainCombinedSearchFullButton("Paperless", "documents"))
        if self.memo_results:
            self.add_item(BrainCombinedSearchFullButton("Memos", "memos"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainCombinedMemoSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainCombinedSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=memo_option_label(item),
                description=memo_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.memo_results)
        ]
        super().__init__(placeholder=f"Memos: {parent.memo_count}", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.memo_results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_memo(str(item.get("name") or ""))
            memo = payload.get("memo")
            if isinstance(memo, dict):
                item = {**item, **memo, "full": True}
            content = render_memo_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Memo open failed: %s", exc)
            await interaction.response.send_message(_tool_failed("메모 열기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        view = BrainOpenedMemoView(self.parent_view.governor_tools, self.parent_view.actor_id, str(item.get("name") or ""), content)
        await interaction.response.defer()
        await interaction.followup.send(content, view=view, allowed_mentions=NO_MENTIONS)
        await self.parent_view.delete_message()
        self.parent_view.stop()


class BrainCombinedDocumentSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainCombinedSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=document_option_label(item),
                description=document_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.document_results)
        ]
        super().__init__(placeholder=f"Paperless: {parent.document_count}", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.document_results[int(self.values[0])]
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
                item if "item" in locals() else {},
                paperless_public_url=self.parent_view.paperless_public_url,
            ),
            allowed_mentions=NO_MENTIONS,
        )
        await self.parent_view.delete_message()
        self.parent_view.stop()


class BrainCombinedSearchFullButton(discord.ui.Button):
    def __init__(self, label: str, target: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.target = target

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, BrainCombinedSearchView):
            await interaction.response.send_message(_tool_failed("조회"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if self.target == "documents":
            view: discord.ui.View = BrainDocumentSearchView(
                parent.governor_tools,
                parent.actor_id,
                parent.query,
                parent.document_results,
                paperless_public_url=parent.paperless_public_url,
            )
            view.bind_message(interaction.message)  # type: ignore[arg-type]
            await interaction.response.edit_message(
                content="",
                embed=_document_search_embed(
                    parent.query,
                    parent.document_results,
                    result_count=parent.document_count,
                    total_count=parent.document_total,
                    paperless_public_url=parent.paperless_public_url,
                ),
                view=view,
                allowed_mentions=NO_MENTIONS,
            )
            parent.stop()
            return
        else:
            payload = {
                "query": parent.query,
                "results": parent.memo_results,
                "resultCount": parent.memo_count,
                "totalCount": parent.memo_total,
            }
            content = render_tool_context(ToolRequest(ToolKind.MEMO_SEARCH, parent.query), payload)
            view = BrainMemoSearchView(
                parent.governor_tools,
                parent.actor_id,
                parent.query,
                parent.memo_results,
                memos_public_url=parent.memos_public_url,
            )
        view.bind_message(interaction.message)  # type: ignore[arg-type]
        await interaction.response.edit_message(content=content, view=view, allowed_mentions=NO_MENTIONS)
        parent.stop()


def _document_search_embed(
    query: str,
    results: list[dict[str, Any]],
    *,
    result_count: int,
    total_count: int,
    paperless_public_url: str,
) -> discord.Embed:
    title = f"Paperless · {query or '..'}"
    embed = discord.Embed(
        title=title[:256],
        description=f"{result_count} results in {total_count} documents",
        color=0x88C0D0,
    )
    lines: list[str] = []
    for index, item in enumerate(results[:25], start=1):
        label = document_option_label(item)
        url = str(item.get("url") or item.get("publicUrl") or document_public_url(paperless_public_url, item.get("id"))).strip()
        line = f"{index}. {label}"
        if url:
            line = f"{line} · [open]({url})"
        lines.append(_discord_embed_line(line, 180))
    if result_count > len(results[:25]):
        lines.append(f"Showing first {len(results[:25])}. Press search in Paperless for the full backend result set.")
    embed.add_field(name="Documents", value="\n".join(lines)[:1024] if lines else "No matching documents.", inline=False)
    return embed


def _discord_embed_line(value: str, limit: int) -> str:
    stripped = " ".join(value.split())
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[: max(0, limit - 3)].rstrip()}..."


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
        super().__init__(placeholder=f"Paperless: {len(parent.results)}", min_values=1, max_values=1, options=options)

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


def render_active_control_message(
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    supplies: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(KST)
    return f"# {current:%Y.%m.%d}({current:%a})"


class BrainActiveControlView(discord.ui.View):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        settings: Settings,
        events: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        supplies: list[dict[str, Any]],
        imports: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.settings = settings
        self.events = events[:ACTIVE_CONTROL_LIMIT]
        self.tasks = tasks[:ACTIVE_CONTROL_LIMIT]
        self.supplies = supplies[:ACTIVE_CONTROL_LIMIT]
        self.imports = imports[:ACTIVE_CONTROL_LIMIT]
        self.add_item(BrainUpcomingEventsSelect(self, self.events))
        self.add_item(BrainActiveControlSelect(self, "tasks", self.tasks))
        self.add_item(BrainActiveControlSelect(self, "supplies", self.supplies))
        self.add_item(BrainImportSelect(self, self.imports))

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

    async def refresh_items(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        events_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.UPCOMING_EVENTS, profile=self.settings.governor_tools_profile)
        )
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
        imports_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.RECENT_IMPORTS, profile=self.settings.governor_tools_profile)
        )
        return _event_results(events_payload), _task_results(tasks_payload), _task_results(supplies_payload), _import_results(imports_payload)

    @discord.ui.button(label="Reload", style=discord.ButtonStyle.primary, row=4)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            events, tasks, supplies, imports = await self.refresh_items()
        except GovernorToolError as exc:
            LOGGER.warning("Active control refresh failed: %s", exc)
            await interaction.followup.send(_tool_failed("Active 갱신"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        kwargs: dict[str, Any] = {
            "content": render_active_control_message(events, tasks, supplies),
            "view": BrainActiveControlView(self.governor_tools, self.settings, events, tasks, supplies, imports),
            "allowed_mentions": NO_MENTIONS,
        }
        month_file = await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
        )
        if month_file is not None:
            kwargs["attachments"] = [month_file]
        await interaction.edit_original_response(**kwargs)


class BrainServiceMenuView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, settings: Settings) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.settings = settings

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == self.settings.guild_id
            and interaction.channel_id == self.settings.brain_channel_id
            and int(interaction.user.id) in self.settings.allowed_user_ids
        ):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label=CALENDAR_LABEL, style=discord.ButtonStyle.secondary)
    async def calendar_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        current = datetime.now(KST).date()
        view = BrainCalendarMonthView(
            self.governor_tools,
            self.settings,
            anchor_date=current,
            year=current.year,
            month=current.month,
        )
        file = await view.month_file()
        kwargs: dict[str, Any] = {
            "content": view.content(),
            "view": view,
            "allowed_mentions": NO_MENTIONS,
        }
        if file is not None:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)

    @discord.ui.button(label=TASKS_SERVICE_BUTTON_LABEL, style=discord.ButtonStyle.secondary)
    async def tasks_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.fetch(
                ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile)
            )
        except GovernorToolError as exc:
            LOGGER.warning("Tasks service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("할 일 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        tasks = _task_results(payload)
        view = BrainActiveTasksView(
            self.governor_tools,
            int(interaction.user.id),
            ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile),
            tasks,
        )
        await interaction.followup.send(
            view.content(),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(label=SUPPLIES_LABEL, style=discord.ButtonStyle.secondary)
    async def supplies_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        request = ToolRequest(
            ToolKind.ACTIVE_TASKS,
            profile="supplies",
            collection_id=self.settings.governor_tools_supplies_collection_id,
        )
        try:
            payload = await self.governor_tools.fetch(request)
        except GovernorToolError as exc:
            LOGGER.warning("Supplies service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("비품 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        supplies = _task_results(payload)
        view = BrainActiveTasksView(self.governor_tools, int(interaction.user.id), request, supplies)
        await interaction.followup.send(
            view.content(),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(label=PAPERLESS_LABEL, style=discord.ButtonStyle.secondary)
    async def paperless_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            f"## {PAPERLESS_TITLE}\n- use `..keyword` to search documents\n- use `..ALL` to browse documents",
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(label=MEMOS_LABEL, style=discord.ButtonStyle.secondary)
    async def memos_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            f"## {MEMOS_TITLE}\n- use `..keyword` to search memos",
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )


class BrainCalendarMonthView(discord.ui.View):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        settings: Settings,
        *,
        anchor_date: date,
        year: int,
        month: int,
        mode: str = "month",
    ) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.settings = settings
        self.anchor_date = anchor_date
        self.year = year
        self.month = month
        self.mode = mode

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == self.settings.guild_id
            and interaction.channel_id == self.settings.brain_channel_id
            and int(interaction.user.id) in self.settings.allowed_user_ids
        ):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def content(self) -> str:
        return f"## {CALENDAR_TITLE} · {self.year}.{self.month:02d}"

    async def weekly_content(self) -> str:
        return await _render_calendar_weekly(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            start=self.anchor_date,
        )

    async def month_file(self) -> discord.File | None:
        return await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            year=self.year,
            month=self.month,
        )

    async def _edit_current(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if self.mode == "weekly":
            kwargs: dict[str, Any] = {
                "content": await self.weekly_content(),
                "view": self,
                "attachments": [],
                "allowed_mentions": NO_MENTIONS,
            }
        else:
            file = await self.month_file()
            kwargs = {
                "content": self.content(),
                "view": self,
                "allowed_mentions": NO_MENTIONS,
            }
            if file is not None:
                kwargs["attachments"] = [file]
        await interaction.edit_original_response(**kwargs)

    @discord.ui.button(label="Month", style=discord.ButtonStyle.secondary, row=0)
    async def month_view(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.mode = "month"
        await self._edit_current(interaction)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=0)
    async def weekly_view(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.mode = "weekly"
        await self._edit_current(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, row=0)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.message.delete()

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary, row=1)
    async def previous_month(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.mode == "weekly":
            self.anchor_date -= timedelta(days=7)
        else:
            self.year, self.month = _shift_month(self.year, self.month, -1)
        await self._edit_current(interaction)

    @discord.ui.button(label="Today", style=discord.ButtonStyle.primary, row=1)
    async def today_month(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        current = datetime.now(KST).date()
        self.anchor_date = current
        self.year = current.year
        self.month = current.month
        await self._edit_current(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary, row=1)
    async def next_month(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.mode == "weekly":
            self.anchor_date += timedelta(days=7)
        else:
            self.year, self.month = _shift_month(self.year, self.month, 1)
        await self._edit_current(interaction)


class BrainUpcomingEventsSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveControlView, events: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.events = events
        options = [
            discord.SelectOption(
                label=_event_option_label(event),
                description=_event_option_description(event) or None,
                value=str(index),
            )
            for index, event in enumerate(events[:ACTIVE_CONTROL_LIMIT])
        ]
        disabled = not options
        if disabled:
            options = [discord.SelectOption(label="No upcoming events", value="empty")]
        super().__init__(placeholder=f"{UPCOMING_EVENTS_LABEL}: {len(events)}", min_values=1, max_values=1, options=options, row=0, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            event = self.events[int(self.values[0])]
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Upcoming event selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("일정 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.followup.send(_render_event_selection(event), allowed_mentions=NO_MENTIONS)


class BrainActiveControlSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveControlView, kind: str, tasks: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.kind = kind
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(
                    task,
                    include_completed=False,
                    supplies=kind == "supplies",
                )
                or None,
                value=str(index),
            )
            for index, task in enumerate(tasks[:ACTIVE_CONTROL_LIMIT])
        ]
        label = SUPPLIES_LABEL if kind == "supplies" else ACTIVE_TASKS_LABEL
        placeholder = f"{label}: {len(tasks)}"
        row = 2 if kind == "supplies" else 1
        disabled = not options
        if disabled:
            label = "No active supplies" if kind == "supplies" else "No active tasks"
            options = [discord.SelectOption(label=label, value="empty")]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, row=row, disabled=disabled)

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


class BrainImportSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveControlView, imports: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.imports = imports
        options = [
            discord.SelectOption(
                label=_import_option_label(item),
                description=_import_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(imports[:ACTIVE_CONTROL_LIMIT])
        ]
        disabled = not options
        if disabled:
            options = [discord.SelectOption(label="No new fax/mail imports", value="empty")]
        super().__init__(placeholder=f"{FAX_MAIL_LABEL}: {len(imports)}", min_values=1, max_values=1, options=options, row=3, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.imports[int(self.values[0])]
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Import selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("Import 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.send_message(_render_import_selection(item), ephemeral=True, allowed_mentions=NO_MENTIONS)


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
        super().__init__(timeout=600)
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
        super().__init__(placeholder=f"{label} {start}-{end}", min_values=1, max_values=1, options=options, row=0)

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
        await interaction.followup.send(
            _render_completed_task_selection(title, task, supplies=self.parent_view.supplies),
            view=BrainCompletedTaskActionsView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                self.parent_view.request,
                task,
            ),
            allowed_mentions=NO_MENTIONS,
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
        await interaction.message.delete()


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


class BrainCompletedTaskActionsView(discord.ui.View):
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
            await interaction.response.send_message(_tool_failed("할 일 다시 만들기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.edit_message(
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
        await interaction.message.delete()

    async def _propose_action(self, interaction: discord.Interaction, action: str) -> None:
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
            await interaction.response.send_message(_tool_failed("완료 할 일 변경"), ephemeral=True, allowed_mentions=NO_MENTIONS)
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


def _event_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("events")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _import_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("imports")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


async def _active_control_month_file_for(
    governor_tools: GovernorToolClient | None,
    *,
    profile: str,
    year: int | None = None,
    month: int | None = None,
) -> discord.File | None:
    if governor_tools is None:
        return None
    try:
        if year is None and month is None:
            payload = await governor_tools.fetch(ToolRequest(ToolKind.CALENDAR_MONTH_IMAGE, profile=profile))
        else:
            payload = await governor_tools.calendar_month_image(profile=profile, year=year, month=month)
        return _month_image_file(payload)
    except (GovernorToolError, AttributeError, ValueError, binascii.Error) as exc:
        LOGGER.warning("Active control month image unavailable: %s", exc)
        return None


def _month_image_file(payload: dict[str, Any]) -> discord.File:
    content_type = str(payload.get("contentType") or "")
    if content_type != "image/png":
        raise ValueError("calendar month image response was not image/png")
    encoded = str(payload.get("contentBase64") or "")
    if not encoded:
        raise ValueError("calendar month image response was empty")
    raw = base64.b64decode(encoded, validate=True)
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("calendar month image response was not a PNG")
    filename = str(payload.get("filename") or "calendar.png").strip() or "calendar.png"
    return discord.File(io.BytesIO(raw), filename=filename)


def _uses_supplies_request(request: ToolRequest) -> bool:
    return request.profile == "supplies" or "supplies" in request.collection_id.lower()


def _render_event_selection(event: dict[str, Any]) -> str:
    title = str(event.get("title") or event.get("summary") or "Untitled event").strip()
    date_text = str(event.get("date") or event.get("startDate") or "").strip()
    time_text = str(event.get("time") or event.get("startTime") or "").strip()
    owner = _event_owner_display(event)
    lines = [f"## {title}"]
    details = [part for part in (date_text, time_text, owner) if part]
    if details:
        lines.append(f"- {' · '.join(details)}")
    return "\n".join(lines)


def _render_import_selection(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Import").strip()
    kind = str(item.get("kind") or "").strip()
    detail = str(item.get("detail") or "").strip()
    lines = [f"## {title}"]
    details = [part for part in (kind, detail) if part]
    if details:
        lines.append(f"- {' · '.join(details)}")
    return "\n".join(lines)


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


def _render_completed_task_selection(title: str, task: dict[str, Any], *, supplies: bool) -> str:
    display = f"~~{title}~~"
    lines = [f"## {display}"]
    if not supplies:
        completed = str(task.get("completedDate") or task.get("completed") or task.get("completedAt") or "").strip()[:10]
        if completed:
            lines.append(f"- completed: {completed}")
    return "\n".join(lines)


def _render_task_service_message(
    title: str,
    tasks: list[dict[str, Any]],
    *,
    page: int,
    history: bool,
    supplies: bool,
    month: date | None = None,
) -> str:
    start = page * TASK_SERVICE_PAGE_SIZE
    page_tasks = tasks[start : start + TASK_SERVICE_PAGE_SIZE]
    if history:
        month_label = f"{month:%Y.%m}" if month else ""
        lines = [f"## {title}", f"### {month_label} • Completed: {len(tasks)}"]
    else:
        showing_start = start + 1 if page_tasks else 0
        showing_end = start + len(page_tasks)
        lines = [f"## {title}", f"- active: {len(tasks)}"]
        if page_tasks:
            lines.append(f"- showing: {showing_start}-{showing_end}")
    for task in page_tasks:
        item_title = str(task.get("title") or task.get("summary") or "Untitled task").strip()
        if history:
            prefix = "~~"
            suffix_marker = "~~"
        else:
            prefix = ""
            suffix_marker = ""
        due = " ".join(
            part
            for part in (
                str(task.get("due") or task.get("dueDate") or "").strip(),
                str(task.get("dueTime") or "").strip(),
            )
            if part
        )
        completed = str(task.get("completedDate") or task.get("completed") or task.get("completedAt") or "").strip()[:10]
        detail = ""
        if due and not supplies and not history:
            detail = f" · {due}"
        escaped_title = discord.utils.escape_markdown(item_title)
        if history and completed and not supplies:
            detail = f" - {prefix}{escaped_title}{suffix_marker}"
            lines.append(f"- {_format_month_day(completed)}{detail}")
            continue
        lines.append(f"- {prefix}{escaped_title}{suffix_marker}{detail}")
    if not page_tasks:
        lines.append("- none")
    return "\n".join(lines)


def _render_active_service_message(title: str, tasks: list[dict[str, Any]], *, supplies: bool = False) -> str:
    lines = [f"## {title}", f"- active: {len(tasks)}"]
    for task in tasks[:25]:
        item_title = str(task.get("title") or task.get("summary") or "Untitled task").strip()
        due = " ".join(
            part
            for part in (
                str(task.get("due") or task.get("dueDate") or "").strip(),
                str(task.get("dueTime") or "").strip(),
            )
            if part
        )
        suffix = f" · {due}" if due and not supplies else ""
        lines.append(f"- {discord.utils.escape_markdown(item_title)}{suffix}")
    if len(tasks) > 25:
        lines.append(f"- {len(tasks) - 25} more")
    if not tasks:
        lines.append("- none")
    return "\n".join(lines)


async def _render_calendar_weekly(governor_tools: GovernorToolClient, *, profile: str, start: date) -> str:
    days = [start + timedelta(days=offset) for offset in range(7)]
    payload = await governor_tools.calendar_week(profile=profile, start=start.isoformat(), days=7)
    raw_items = payload.get("items")
    items = [dict(item) for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    payloads = {str(item.get("date") or ""): item for item in items}
    lines = [f"## {CALENDAR_TITLE} · 𝓦𝓮𝓮𝓴𝓵𝔂", f"- {days[0]:%Y.%m.%d} - {days[-1]:%Y.%m.%d}"]
    for value in days:
        day_payload = payloads.get(value.isoformat())
        if day_payload is None:
            continue
        events = _event_results(day_payload)
        if not events:
            continue
        weather = day_payload.get("weather")
        weather_summary = str(weather.get("summary") or "").strip() if isinstance(weather, dict) else ""
        suffix = f" • {weather_summary}" if weather_summary else ""
        lines.append("")
        lines.append(f"### {value:%Y.%m.%d %a}{suffix}")
        lines.extend(_calendar_weekly_event_line(item) for item in events[:8])
    if len(lines) == 2:
        lines.append("- 일정 없음")
    return "\n".join(lines)[:1990]


def _calendar_weekly_event_line(event: dict[str, Any]) -> str:
    time_text = str(event.get("time") or event.get("startTime") or "").strip()
    title = discord.utils.escape_markdown(str(event.get("title") or event.get("summary") or "Untitled event").strip())
    prefix = f"{time_text} " if time_text else ""
    return f"- {prefix}{title}{_calendar_event_owner_suffix(event)}"


def _calendar_event_owner_suffix(event: dict[str, Any]) -> str:
    owner = _event_owner_display(event)
    if owner == FAMILY_EVENT_MARKER:
        return FAMILY_EVENT_SUFFIX
    if owner == PERSONAL_EVENT_MARKER:
        return f"  • {PERSONAL_EVENT_MARKER}"
    return ""


def _event_owner_display(event: dict[str, Any]) -> str:
    owner = str(event.get("ownerLabel") or event.get("owner") or "").strip()
    normalized = owner.lower().replace("_", "").replace(" ", "")
    if normalized == "family":
        return FAMILY_EVENT_MARKER
    if normalized in {"gddzin", "personal", "main"}:
        return PERSONAL_EVENT_MARKER
    return owner


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _shift_date_month(value: date, delta: int) -> date:
    year, month = _shift_month(value.year, value.month, delta)
    return date(year, month, 1)


def _month_end(value: date) -> date:
    return _shift_date_month(value, 1) - timedelta(days=1)


def _format_month_day(value: str) -> str:
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value[:10]
    return f"{parsed.day:02d}.{KOREAN_SHORT_WEEKDAYS[parsed.weekday()]}"


def _task_option_label(task: dict[str, Any]) -> str:
    return _compact_select_text(str(task.get("title") or task.get("summary") or "Untitled task"), 100)


def _event_option_label(event: dict[str, Any]) -> str:
    title = str(event.get("title") or event.get("summary") or "Untitled event")
    return _compact_select_text(title, 100)


def _event_option_description(event: dict[str, Any]) -> str:
    date_text = str(event.get("date") or event.get("startDate") or "").strip()
    time_text = str(event.get("time") or event.get("startTime") or "").strip()
    owner = _event_owner_display(event)
    return _compact_select_text(" · ".join(part for part in (date_text, time_text, owner) if part), 100)


def _import_option_label(item: dict[str, Any]) -> str:
    return _compact_select_text(str(item.get("title") or "Import"), 100)


def _import_option_description(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "").strip()
    detail = str(item.get("detail") or "").strip()
    return _compact_select_text(" · ".join(part for part in (kind, detail) if part), 100)


def _task_option_description(
    task: dict[str, Any],
    *,
    include_completed: bool = True,
    supplies: bool = False,
) -> str:
    if supplies:
        return ""
    completed = (
        str(task.get("completedDate") or task.get("completed") or task.get("completedAt") or "").strip()[:10]
        if include_completed
        else ""
    )
    due = str(task.get("due") or task.get("dueDate") or "").strip()
    due_time = str(task.get("dueTime") or "").strip()
    due_text = " ".join(part for part in (due, due_time) if part)
    parts = [part for part in (completed, due_text) if part]
    return _compact_select_text(" · ".join(parts), 100)


def _compact_select_text(value: str, limit: int) -> str:
    text = " ".join(value.split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
