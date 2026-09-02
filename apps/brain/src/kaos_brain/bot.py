from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
import re
from typing import Any

import discord

from .brain_guard import BrainGuardContext, BrainGuardError, BrainGuardResult, adapt_kaosai_plan
from .config import Settings
from .discord_active_control_views import (
    BrainActiveControlSelect,
    BrainActiveControlView,
    BrainImportSelect,
    BrainServiceMenuSelect,
    BrainServiceMenuView,
    BrainUpcomingEventsSelect,
    _read_active_control_message_id,
    _read_active_control_service_message_id,
    _read_open_service_message_id,
    _write_active_control_message_id,
)
from .discord_active_control_handlers import BrainActiveControlMixin, _is_transient_brain_message
from .discord_calendar_views import BrainCalendarMonthView
from .discord_confirmation_views import (
    DocumentTagConfirmationView,
    EventCreateConfirmationView,
    MemoCreateConfirmationView,
    MemoDeleteConfirmationView,
    MemoEditConfirmationView,
)
from .discord_content_views import (
    BrainCombinedSearchFullButton,
    BrainCombinedSearchView,
    BrainDeletedMemoView,
    BrainDocumentSearchSelect,
    BrainDocumentSearchView,
    BrainMemoDeleteConfirmView,
    BrainMemoEditConfirmView,
    BrainMemoSearchSelect,
    BrainMemoSearchView,
    BrainOpenedDocumentView,
    BrainOpenedMemoView,
    _linked_document_results,
)
from .discord_fax_mail_views import BrainFaxMailSelect, BrainFaxMailView
from .discord_task_views import (
    BrainActiveTaskActionsView,
    BrainActiveTasksSelect,
    BrainActiveTasksView,
    BrainCompletedTaskActionsView,
    BrainCompletedTasksSelect,
    BrainCompletedTasksView,
    BrainTaskEditModal,
    BrainTaskHistorySelect,
    TaskActionConfirmationView,
    TaskCreateConfirmationView,
    TaskEditConfirmationView,
    TaskUpdateConfirmationView,
)
from .discord_proposal_handlers import BrainProposalMixin
from .discord_tool_responses import answer_with_governor_tool
from .discord_formatting import (
    ACTIVE_CONTROL_HISTORY_LIMIT,
    ACTIVE_TASKS_LABEL,
    ACTIVE_TASKS_TITLE,
    CALENDAR_LABEL,
    CALENDAR_TITLE,
    FAX_MAIL_LABEL,
    FAX_MAIL_PAGE_SIZE,
    FAX_MAIL_TITLE,
    KST,
    MEMOS_LABEL,
    MEMOS_TITLE,
    PAPERLESS_LABEL,
    PAPERLESS_TITLE,
    SUPPLIES_LABEL,
    SUPPLIES_TITLE,
    TASKS_SERVICE_BUTTON_LABEL,
    UPCOMING_EVENTS_LABEL,
    _compact_select_text,
    _event_results,
    _fax_mail_results,
    _format_month_day,
    _has_overdue_tasks,
    _import_kind,
    _import_results,
    _range_summary,
    _render_active_service_message,
    _render_active_task_selection,
    _safe_discord_line,
    _shift_date_month,
    _task_option_description,
    _task_option_label,
    _task_results,
    render_active_control_message,
)
from .discord_view_helpers import (
    NO_MENTIONS,
    _bind_view_message,
)
from .event_intent import EventCreateRequest, event_create_needs_date, parse_event_create
from .governor_tools import (
    GovernorToolClient,
    GovernorToolConfig,
    TaskEditRequest as GovernorTaskEditRequest,
    SEARCH_RESULT_LIMIT,
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
FAX_RECEIVED_NOTIFICATION_PREFIX = "Fax received."
DOCUMENT_TAG_SUGGESTION_PATTERN = re.compile(r"\b(?:document|doc|문서)?\s*(\d{1,9})\b")
OPENAI_CALLBACK_PREFIX = "http://localhost:1455/auth/callback?"
OPENAI_CODE_PATTERN = re.compile(r"^ac_[A-Za-z0-9_.-]+$")
KAOSAI_CLARIFY_WINDOW_SECONDS = 300


def _is_active_control_quiet_hour(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


@dataclass(frozen=True)
class _PendingKaosAIClarification:
    original_text: str
    question: str
    created_at: datetime


def _combine_clarification_answer(original_text: str, answer: str) -> str:
    original = " ".join(original_text.strip().split())
    cleaned_answer = " ".join(answer.strip().split())
    if not original or not cleaned_answer:
        return original_text
    event_match = re.match(r"^(?P<prefix>일정|event)\s*[,，;；:：]\s*(?P<body>.+)$", original, flags=re.IGNORECASE)
    if event_match is not None and _looks_like_date_answer(cleaned_answer):
        return f"{event_match.group('prefix')}, {cleaned_answer} {event_match.group('body').strip()}"
    return f"{original}\n답변: {cleaned_answer}"


def _looks_like_date_answer(text: str) -> bool:
    lowered = text.lower()
    if lowered in {"오늘", "내일", "모레", "today", "tomorrow"}:
        return True
    return re.fullmatch(r"(?:(?:\d{4})[-./년]\s*)?\d{1,2}[-./월]\s*\d{1,2}일?", text) is not None


def _message_kst_datetime(message: discord.Message) -> datetime:
    created_at = getattr(message, "created_at", None)
    if not isinstance(created_at, datetime):
        return datetime.now(KST)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(KST)


def _message_kst_date(message: discord.Message) -> date:
    return _message_kst_datetime(message).date()


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


def _is_active_control_reload_command(text: str) -> bool:
    return text.strip().lower() == "/rrr"


def _looks_like_auth_failure(text: str) -> bool:
    lowered = text.lower()
    return "token_expired" in lowered or "authentication failed" in lowered or "401" in lowered


async def _start_reauth_message(reauth: OpenClawReauthClient) -> str:
    try:
        payload = await reauth.start()
    except ReauthError as exc:
        return f"KaosBrain-OpenAI login renewal failed to start: `{exc}`"
    oauth_url = str(payload.get("oauthUrl") or "").strip()
    status = str(payload.get("status") or "").strip() or "unknown"
    if not oauth_url:
        return f"KaosBrain-OpenAI login renewal started, but no login URL is available yet. Status: `{status}`"
    return "\n".join(
        [
            "## KaosBrain-OpenAI login renewal",
            "Open this URL, sign in, then paste the callback URL here.",
            oauth_url,
        ]
    )


def _render_kaosai_clarify_preview(plan: dict[str, Any]) -> str:
    parameters = plan.get("parameters")
    question = _preview_value(parameters.get("question")) if isinstance(parameters, dict) else ""
    lines = ["## KaosBrain-OpenAI plan", "intent: clarify", "confirmation: not required"]
    if question:
        lines.append(f"- question: {question}")
    lines.append("- execution: skipped")
    return "\n".join(lines)


def _render_kaosai_rejected_preview(plan: dict[str, Any], reason: str) -> str:
    intent = _preview_value(plan.get("intent")) or "unknown"
    scope = _preview_value(plan.get("scope"))
    lines = ["## KaosBrain-OpenAI rejected", f"reason: `{reason}`", f"intent: {intent}"]
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
        "## KaosBrain-OpenAI plan",
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
        if request.memo:
            lines.append(f"- memo: {_preview_value(request.memo, limit=120)}")
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


class BrainBot(BrainProposalMixin, BrainActiveControlMixin, discord.Client):
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
        self._active_control_repost_task: asyncio.Task[None] | None = None
        self._pending_kaosai_clarifications: dict[tuple[int, int], _PendingKaosAIClarification] = {}

    async def on_ready(self) -> None:
        LOGGER.info("KaosBrain connected as %s", self.user)
        if self.governor_tools is not None and (
            self._active_control_refresh_task is None or self._active_control_refresh_task.done()
        ):
            self._active_control_refresh_task = asyncio.create_task(self._ensure_active_control_message())
        if (
            self.governor_tools is not None
            and self.settings.active_control_repost_seconds > 0
            and (self._active_control_repost_task is None or self._active_control_repost_task.done())
        ):
            self._active_control_repost_task = asyncio.create_task(
                self._active_control_repost_loop(),
                name="kaosbrain-active-control-repost",
            )

    async def close(self) -> None:
        for task in (self._active_control_refresh_task, self._active_control_repost_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._active_control_refresh_task, self._active_control_repost_task) if task is not None),
            return_exceptions=True,
        )
        self._active_control_refresh_task = None
        self._active_control_repost_task = None
        await super().close()

    async def _active_control_repost_loop(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(self.settings.active_control_repost_seconds)
            if self.is_closed():
                return
            if _is_active_control_quiet_hour(
                datetime.now(KST).hour,
                self.settings.active_control_quiet_start_hour,
                self.settings.active_control_quiet_end_hour,
            ):
                continue
            await self._ensure_active_control_message(move_to_bottom=True)

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
            if (
                message.guild is not None
                and message.guild.id == self.settings.guild_id
                and message.channel.id == self.settings.notification_channel_id
                and message.author.id == self.settings.governor_bot_user_id
                and str(message.content or "").startswith(FAX_RECEIVED_NOTIFICATION_PREFIX)
            ):
                await self._ensure_active_control_message()
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
        if _is_active_control_reload_command(text):
            await self._reload_active_control_from_message(message)
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
        request_text = self._consume_kaosai_clarification_answer(message, request.text)
        if request.route is Route.CHAT and self.settings.kaosai_dry_run_enabled:
            async with message.channel.typing():
                reply = await self._render_kaosai_diagnostic(request_text, message=message)
            await message.reply(
                reply[: self.settings.max_reply_chars],
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        task_update = (
            parse_task_due_update(request_text, today=_message_kst_date(message))
            if request.route is Route.CHAT
            else None
        )
        if task_update is not None:
            await self._propose_task_due_update(message, task_update)
            return
        task_edit = parse_task_edit(request_text) if request.route is Route.CHAT else None
        if task_edit is not None:
            await self._propose_task_edit(message, task_edit)
            return
        task_create = (
            parse_task_create(request_text, today=_message_kst_date(message))
            if request.route is Route.CHAT
            else None
        )
        if task_create is not None:
            await self._propose_task_create(message, task_create)
            return
        task_action = parse_task_action(request_text) if request.route is Route.CHAT else None
        if task_action is not None:
            await self._propose_task_action(message, task_action)
            return
        event_create = (
            parse_event_create(request_text, today=_message_kst_date(message))
            if request.route is Route.CHAT
            else None
        )
        if event_create is not None:
            await self._propose_event_create(message, event_create)
            return
        missing_event_date = event_create_needs_date(request_text) if request.route is Route.CHAT else ""
        if missing_event_date:
            self._remember_kaosai_clarification(
                message,
                request_text,
                f"{missing_event_date} 일정을 등록할 날짜가 언제인가요?",
            )
            await message.reply(
                f"{missing_event_date} 일정을 등록할 날짜가 언제인가요?",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        memo_edit = parse_memo_edit(request_text) if request.route is Route.CHAT else None
        if memo_edit is not None:
            await self._propose_memo_edit(message, memo_edit)
            return
        memo_delete = parse_memo_delete(request_text) if request.route is Route.CHAT else None
        if memo_delete is not None:
            await self._propose_memo_delete(message, memo_delete)
            return
        memo_create = parse_memo_create(request_text) if request.route is Route.CHAT else None
        if memo_create is not None:
            await self._propose_memo_create(message, memo_create)
            return
        document_tag_suggestion = parse_document_tag_suggestion(request_text) if request.route is Route.CHAT else ""
        if document_tag_suggestion:
            await self._propose_document_tag_suggestion(message, document_tag_suggestion)
            return
        tool_request = (
            parse_tool_request(request_text, today=_message_kst_date(message))
            if request.route is Route.CHAT
            else None
        )
        if tool_request is not None:
            async with message.channel.typing():
                reply, view = await self._answer_with_governor_tool(request_text, tool_request, actor_id=int(message.author.id))
            sent = await message.reply(
                reply[: self.settings.max_reply_chars],
                view=view,
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            _bind_view_message(view, sent)
            return
        view: discord.ui.View | None = None
        async with message.channel.typing():
            try:
                if request.route is Route.CHAT and self.settings.kaosai_chat_enabled:
                    kaosai_reply = await self._answer_with_kaosai_plan(request_text, message=message)
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
                if request.route is Route.CHAT and self.settings.auto_route_enabled:
                    reply = await self.ollama.generate_auto(request_text)
                else:
                    reply = await self.ollama.generate(request.route, request_text)
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

    def _pending_kaosai_store(self) -> dict[tuple[int, int], _PendingKaosAIClarification]:
        store = getattr(self, "_pending_kaosai_clarifications", None)
        if store is None:
            store = {}
            self._pending_kaosai_clarifications = store
        return store

    def _clarification_key(self, message: discord.Message) -> tuple[int, int]:
        return (int(message.channel.id), int(message.author.id))

    def _consume_kaosai_clarification_answer(self, message: discord.Message, user_text: str) -> str:
        store = self._pending_kaosai_store()
        key = self._clarification_key(message)
        pending = store.pop(key, None)
        if pending is None:
            return user_text
        now = _message_kst_datetime(message)
        if now - pending.created_at > timedelta(seconds=KAOSAI_CLARIFY_WINDOW_SECONDS):
            return user_text
        answer = user_text.strip()
        if not answer:
            return user_text
        return _combine_clarification_answer(pending.original_text, answer)

    def _remember_kaosai_clarification(self, message: discord.Message, user_text: str, question: str) -> None:
        self._pending_kaosai_store()[self._clarification_key(message)] = _PendingKaosAIClarification(
            original_text=user_text.strip(),
            question=question.strip(),
            created_at=_message_kst_datetime(message),
        )

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
                    "today": _message_kst_date(message).isoformat(),
                },
            )
        except KaosAIError as exc:
            LOGGER.warning("KaosAI planner failed: %s", exc)
            if self.reauth is not None and _looks_like_auth_failure(str(exc)):
                return (
                    "## KaosBrain-OpenAI login expired\nRenew ChatGPT login.",
                    KaosAIReauthView(self.reauth, int(message.author.id)),
                )
            return None
        if plan is None:
            return None
        if str(plan.get("intent") or "").strip() == "clarify":
            parameters = plan.get("parameters")
            question = str(parameters.get("question") or "").strip() if isinstance(parameters, dict) else ""
            self._remember_kaosai_clarification(message, user_text, question or "조금 더 자세히 말해줘요.")
            return (question or "조금 더 자세히 말해줘요.", None)
        try:
            guarded = adapt_kaosai_plan(
                plan,
                BrainGuardContext(
                    actor_id=int(message.author.id),
                    idempotency_key=f"discord:{message.id}",
                    today=_message_kst_date(message),
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
                "KaosBrain-OpenAI reauth agent is not enabled.",
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
                reply = f"KaosBrain-OpenAI login renewal failed: `{exc}`"
            else:
                status = str(payload.get("status") or "")
                if status == "succeeded":
                    reply = "KaosBrain-OpenAI login renewed."
                else:
                    reply = f"KaosBrain-OpenAI login renewal status: `{status or 'unknown'}`"
        await message.channel.send(reply[: self.settings.max_reply_chars], allowed_mentions=NO_MENTIONS)

    async def _render_kaosai_diagnostic(self, user_text: str, *, message: discord.Message) -> str:
        try:
            plan = await self.kaosai.plan(
                user_text,
                context={
                    "actorId": str(message.author.id),
                    "channelId": str(message.channel.id),
                    "today": _message_kst_date(message).isoformat(),
                },
            )
        except KaosAIError as exc:
            return f"## KaosBrain-OpenAI diagnostic\n- planner: failed `{exc}`"
        if plan is None:
            return "## KaosBrain-OpenAI diagnostic\n- planner: unavailable"
        if str(plan.get("intent") or "").strip() == "clarify":
            return _render_kaosai_clarify_preview(plan)
        try:
            guarded = adapt_kaosai_plan(
                plan,
                BrainGuardContext(
                    actor_id=int(message.author.id),
                    idempotency_key=f"discord-diagnostic:{message.id}",
                    today=_message_kst_date(message),
                    default_profile=self.settings.governor_tools_profile,
                    supplies_collection_id=self.settings.governor_tools_supplies_collection_id,
                ),
            )
        except BrainGuardError as exc:
            return _render_kaosai_rejected_preview(plan, str(exc))
        return _render_kaosai_guard_preview(guarded)

    async def _answer_with_governor_tool(
        self,
        user_text: str,
        tool_request: ToolRequest,
        *,
        actor_id: int,
    ) -> tuple[str, discord.ui.View | None]:
        return await answer_with_governor_tool(
            governor_tools=self.governor_tools,
            settings=getattr(self, "settings", None),
            ollama=getattr(self, "ollama", None),
            user_text=user_text,
            tool_request=tool_request,
            actor_id=actor_id,
            logger=LOGGER,
        )

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
