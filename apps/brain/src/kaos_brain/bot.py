from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any

import discord

from .brain_guard import BrainGuardContext, BrainGuardError, BrainGuardResult, BrainGuardResultKind, adapt_kaosai_plan
from .config import Settings
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
from .discord_tool_responses import answer_with_governor_tool
from .discord_formatting import (
    ACTIVE_CONTROL_HISTORY_LIMIT,
    ACTIVE_CONTROL_LIMIT,
    ACTIVE_CONTROL_MARKER,
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
    SERVICE_MENU_MARKER,
    SUPPLIES_LABEL,
    SUPPLIES_TITLE,
    TASKS_SERVICE_BUTTON_LABEL,
    UPCOMING_EVENTS_LABEL,
    _active_control_month_file_for,
    _active_fax_mail_imports,
    _compact_select_text,
    _event_option_description,
    _event_option_label,
    _event_results,
    _fax_mail_results,
    _format_month_day,
    _has_overdue_tasks,
    _import_kind,
    _import_option_description,
    _import_option_label,
    _import_results,
    _range_summary,
    _render_active_service_message,
    _render_active_task_selection,
    _render_calendar_weekly,
    _render_document_list_message,
    _render_event_selection,
    _render_import_selection,
    _render_memo_list_message,
    _safe_discord_line,
    _payload_count,
    _shift_date_month,
    _shift_month,
    _task_option_description,
    _task_option_label,
    _task_results,
    _week_start_sunday,
    render_active_control_message,
)
from .discord_view_helpers import (
    NO_MENTIONS,
    BrainAutoClosingView,
    BrainTemporarySearchView,
    _bind_view_message,
    _defer_component_update,
    _edit_deferred_component,
    _followup_with_bound_view,
    _reply_with_bound_view,
)
from .event_intent import EventCreateRequest, parse_event_create
from .governor_tools import (
    DocumentTagRequest,
    GovernorToolClient,
    GovernorToolConfig,
    GovernorToolError,
    TaskEditRequest as GovernorTaskEditRequest,
    render_memo_create_completed,
    render_memo_create_proposal,
    render_memo_delete_completed,
    render_memo_delete_proposal,
    render_memo_edit_completed,
    render_memo_edit_proposal,
    render_document_tags_completed,
    render_document_tags_proposal,
    render_event_create_completed,
    render_event_create_proposal,
    render_task_action_proposal,
    render_task_create_proposal,
    render_task_edit_proposal,
    render_task_due_update_proposal,
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
DOCUMENT_TAG_SUGGESTION_PATTERN = re.compile(r"\b(?:document|doc|문서)?\s*(\d{1,9})\b")
OPENAI_CALLBACK_PREFIX = "http://localhost:1455/auth/callback?"
OPENAI_CODE_PATTERN = re.compile(r"^ac_[A-Za-z0-9_.-]+$")
KAOSAI_CLARIFY_WINDOW_SECONDS = 300


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


async def _delete_open_service_message(settings: Settings, interaction: discord.Interaction) -> None:
    state_path = getattr(settings, "active_control_state_path", "")
    message_id = _read_open_service_message_id(state_path)
    if not message_id:
        return
    try:
        channel = await _interaction_brain_channel(settings, interaction)
        if channel is None:
            return
        message = await channel.fetch_message(message_id)
        await message.delete()
    except discord.HTTPException:
        LOGGER.info("Open Brain service message %s was already unavailable", message_id)
    finally:
        _write_active_control_message_id(state_path, 0, open_service_message_id=0)


async def _send_single_service_message(
    settings: Settings,
    interaction: discord.Interaction,
    *args: Any,
    **kwargs: Any,
) -> discord.Message | None:
    await _delete_open_service_message(settings, interaction)
    kwargs.setdefault("allowed_mentions", NO_MENTIONS)
    kwargs.setdefault("wait", True)
    message = await interaction.followup.send(*args, **kwargs)
    _bind_view_message(kwargs.get("view"), message)
    try:
        message_id = int(getattr(message, "id", 0) or 0)
    except (TypeError, ValueError):
        message_id = 0
    if message_id > 0:
        _write_active_control_message_id(
            getattr(settings, "active_control_state_path", ""),
            0,
            open_service_message_id=message_id,
        )
    return message if isinstance(message, discord.Message) else None


async def _interaction_brain_channel(
    settings: Settings,
    interaction: discord.Interaction,
) -> Any | None:
    channel = getattr(interaction, "channel", None)
    if isinstance(channel, discord.TextChannel | discord.Thread):
        return channel
    if callable(getattr(channel, "fetch_message", None)):
        return channel
    client = getattr(interaction, "client", None)
    if client is None:
        return None
    get_channel = getattr(client, "get_channel", None)
    if callable(get_channel):
        channel = get_channel(settings.brain_channel_id)
        if isinstance(channel, discord.TextChannel | discord.Thread):
            return channel
        if callable(getattr(channel, "fetch_message", None)):
            return channel
    fetch_channel = getattr(client, "fetch_channel", None)
    if callable(fetch_channel):
        try:
            channel = await fetch_channel(settings.brain_channel_id)
        except discord.HTTPException:
            return None
        if isinstance(channel, discord.TextChannel | discord.Thread):
            return channel
        if callable(getattr(channel, "fetch_message", None)):
            return channel
    return None


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


def _read_open_service_message_id(path: str) -> int:
    return _read_active_control_state_value(path, "openServiceMessageId")


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


def _write_active_control_message_id(
    path: str,
    message_id: int,
    service_message_id: int = 0,
    *,
    open_service_message_id: int | None = None,
) -> None:
    if not path or (message_id <= 0 and service_message_id <= 0 and open_service_message_id is None):
        return
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, int] = {}
    try:
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload.update(
                {
                    key: int(value)
                    for key, value in existing.items()
                    if key in {"messageId", "serviceMessageId", "openServiceMessageId"}
                }
            )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        payload = {}
    if message_id > 0:
        payload["messageId"] = message_id
    if service_message_id > 0:
        payload["serviceMessageId"] = service_message_id
    if open_service_message_id is not None:
        if open_service_message_id > 0:
            payload["openServiceMessageId"] = open_service_message_id
        else:
            payload.pop("openServiceMessageId", None)
    tmp_path = state_path.with_suffix(f"{state_path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp_path.replace(state_path)


def _tool_cancelled(action: str) -> str:
    return f"{action} 취소했어요."


def _is_transient_brain_message(content: str) -> bool:
    normalized = content.strip()
    if not normalized:
        return False
    if normalized.startswith(ACTIVE_CONTROL_MARKER) or normalized == SERVICE_MENU_MARKER:
        return False
    if normalized.startswith(("Confirm ", "## Confirm ")):
        return True
    if "실패했어요." in normalized or "취소했어요." in normalized:
        return True
    return normalized in {
        "Task added.",
        "Supply added.",
        "일정 저장했어요.",
        "메모 저장했어요.",
        "할 일 수정했어요.",
        "할 일 삭제했어요.",
        "할 일 완료했어요.",
        "할 일 다시 열었어요.",
        "비품 수정했어요.",
        "비품 삭제했어요.",
        "비품 완료했어요.",
        "비품 다시 열었어요.",
    }


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
                return ("## KaosAI login expired\nRenew ChatGPT login.", KaosAIReauthView(self.reauth, int(message.author.id)))
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
                    "today": _message_kst_date(message).isoformat(),
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
                    today=_message_kst_date(message),
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
        return await answer_with_governor_tool(
            governor_tools=self.governor_tools,
            settings=getattr(self, "settings", None),
            ollama=getattr(self, "ollama", None),
            user_text=user_text,
            tool_request=tool_request,
            actor_id=actor_id,
            logger=LOGGER,
        )

    async def _reload_active_control_from_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.warning("Failed to delete active control reload command")
        await self._ensure_active_control_message(move_to_bottom=True)

    async def _ensure_active_control_message(self, *, move_to_bottom: bool = False) -> None:
        if self.governor_tools is None or self.user is None:
            return
        try:
            channel = self.get_channel(self.settings.brain_channel_id) or await self.fetch_channel(self.settings.brain_channel_id)
            if not isinstance(channel, discord.TextChannel | discord.Thread):
                return
            events, tasks, supplies, imports = await self._active_control_items()
            current = datetime.now(KST)
            month_file = await self._active_control_month_file(today=current.date())
            content = render_active_control_message(events, tasks, supplies, now=current)
            view = BrainActiveControlView(self.governor_tools, self.settings, events, tasks, supplies, imports)
            message = await self._find_active_control_message(channel)
            service_message = await self._find_active_control_service_message(channel)
            if move_to_bottom:
                await self._delete_recent_transient_brain_messages(channel)
                if message is not None:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        LOGGER.warning("Failed to delete old active control message")
                    message = None
                if service_message is not None:
                    try:
                        await service_message.delete()
                    except discord.HTTPException:
                        LOGGER.warning("Failed to delete old active control service message")
                    service_message = None
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

    async def _delete_recent_transient_brain_messages(self, channel: discord.TextChannel | discord.Thread) -> None:
        if self.user is None:
            return
        async for message in channel.history(limit=ACTIVE_CONTROL_HISTORY_LIMIT):
            if message.author.id != self.user.id:
                continue
            if not _is_transient_brain_message(str(message.content or "")):
                continue
            try:
                await message.delete()
            except discord.HTTPException:
                LOGGER.warning("Failed to delete transient Brain message %s", getattr(message, "id", ""))

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

    async def _active_control_month_file(self, *, today: date) -> discord.File | None:
        return await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            today=today,
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
        await _reply_with_bound_view(
            message,
            render_task_due_update_proposal(payload),
            view=TaskUpdateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        await _reply_with_bound_view(
            message,
            render_task_create_proposal(payload),
            view=TaskCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        await _reply_with_bound_view(
            message,
            render_task_action_proposal(payload),
            view=TaskActionConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        await _reply_with_bound_view(
            message,
            render_task_edit_proposal(payload),
            view=TaskEditConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        await _reply_with_bound_view(
            message,
            render_event_create_proposal(payload),
            view=EventCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        await _reply_with_bound_view(
            message,
            render_memo_create_proposal(payload),
            view=MemoCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        await _reply_with_bound_view(
            message,
            render_memo_delete_proposal(payload),
            view=MemoDeleteConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        await _reply_with_bound_view(
            message,
            render_memo_edit_proposal(payload),
            view=MemoEditConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
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
        self.imports = _active_fax_mail_imports(imports)[:ACTIVE_CONTROL_LIMIT]
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
        current = datetime.now(KST)
        kwargs: dict[str, Any] = {
            "content": render_active_control_message(events, tasks, supplies, now=current),
            "view": BrainActiveControlView(self.governor_tools, self.settings, events, tasks, supplies, imports),
            "allowed_mentions": NO_MENTIONS,
        }
        month_file = await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            today=current.date(),
        )
        if month_file is not None:
            kwargs["attachments"] = [month_file]
        await interaction.edit_original_response(**kwargs)


class BrainServiceMenuView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, settings: Settings) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.settings = settings
        self.add_item(BrainServiceMenuSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == self.settings.guild_id
            and interaction.channel_id == self.settings.brain_channel_id
            and int(interaction.user.id) in self.settings.allowed_user_ids
        ):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def open_calendar(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        current = datetime.now(KST).date()
        view = BrainCalendarMonthView(
            self.governor_tools,
            self.settings,
            anchor_date=current,
            year=current.year,
            month=current.month,
            mode="weekly",
        )
        kwargs: dict[str, Any] = {
            "content": await view.weekly_content(),
            "view": view,
            "allowed_mentions": NO_MENTIONS,
        }
        await _send_single_service_message(self.settings, interaction, **kwargs)

    async def open_tasks(self, interaction: discord.Interaction) -> None:
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
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content(),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_supplies(self, interaction: discord.Interaction) -> None:
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
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content(),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_paperless(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.documents("", page=1, limit=SEARCH_RESULT_LIMIT)
        except GovernorToolError as exc:
            LOGGER.warning("Paperless service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("Paperless 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        results = _linked_document_results(search_results(payload), self.settings.paperless_public_url)
        result_count = _payload_count(payload, "resultCount", "count", fallback=len(results))
        total_count = _payload_count(payload, "totalCount", "total", fallback=result_count)
        page = _payload_count(payload, "page", fallback=1)
        page_size = _payload_count(payload, "pageSize", "page_size", fallback=SEARCH_RESULT_LIMIT)
        view = (
            BrainDocumentSearchView(
                self.governor_tools,
                int(interaction.user.id),
                "",
                results,
                result_count=result_count,
                total_count=total_count,
                page=page,
                page_size=page_size,
                paperless_public_url=self.settings.paperless_public_url,
            )
            if results
            else None
        )
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content()
            if view is not None
            else _render_document_list_message(
                "",
                results,
                result_count=result_count,
                total_count=total_count,
                page=page,
                page_size=page_size,
                searched=False,
            ),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_memos(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        request = ToolRequest(ToolKind.MEMO_SEARCH, "")
        try:
            payload = await self.governor_tools.fetch(request)
        except GovernorToolError as exc:
            LOGGER.warning("Memos service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("Memos 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        results = search_results(payload)
        view = (
            BrainMemoSearchView(
                self.governor_tools,
                int(interaction.user.id),
                "",
                results,
                result_count=_payload_count(payload, "resultCount", "count", fallback=len(results)),
                total_count=_payload_count(payload, "totalCount", fallback=len(results)),
                memos_public_url=self.settings.memos_public_url,
            )
            if results
            else None
        )
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content() if view is not None else _render_memo_list_message(
                "",
                results,
                result_count=_payload_count(payload, "resultCount", "count", fallback=len(results)),
                total_count=_payload_count(payload, "totalCount", fallback=len(results)),
                searched=False,
            ),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_fax_mail(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.fetch(
                ToolRequest(ToolKind.RECENT_IMPORTS, profile=self.settings.governor_tools_profile)
            )
        except GovernorToolError as exc:
            LOGGER.warning("Fax Mail service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("Fax Mail 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        imports = _fax_mail_results(payload, mode="incoming")
        view = BrainFaxMailView(
            self.governor_tools,
            int(interaction.user.id),
            self.settings,
            imports,
            mode="incoming_fax",
        )
        await _send_single_service_message(self.settings, interaction, view.content(), view=view, allowed_mentions=NO_MENTIONS)


class BrainServiceMenuSelect(discord.ui.Select):
    def __init__(self, service_menu: BrainServiceMenuView) -> None:
        self.service_menu = service_menu
        super().__init__(
            placeholder="Select one.",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=CALENDAR_LABEL, value="calendar"),
                discord.SelectOption(label=TASKS_SERVICE_BUTTON_LABEL, value="tasks"),
                discord.SelectOption(label=SUPPLIES_LABEL, value="supplies"),
                discord.SelectOption(label=PAPERLESS_LABEL, value="paperless"),
                discord.SelectOption(label=MEMOS_LABEL, value="memos"),
                discord.SelectOption(label=FAX_MAIL_LABEL, value="fax_mail"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0] if self.values else ""
        if selected == "calendar":
            await self.service_menu.open_calendar(interaction)
        elif selected == "tasks":
            await self.service_menu.open_tasks(interaction)
        elif selected == "supplies":
            await self.service_menu.open_supplies(interaction)
        elif selected == "paperless":
            await self.service_menu.open_paperless(interaction)
        elif selected == "memos":
            await self.service_menu.open_memos(interaction)
        elif selected == "fax_mail":
            await self.service_menu.open_fax_mail(interaction)
        else:
            await interaction.response.send_message("Unknown service.", ephemeral=True, allowed_mentions=NO_MENTIONS)


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
        super().__init__(timeout=None)
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
            start=_week_start_sunday(self.anchor_date),
        )

    async def month_file(self) -> discord.File | None:
        return await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            year=self.year,
            month=self.month,
            today=datetime.now(KST).date(),
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
        await interaction.response.defer()
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
        if kind == "tasks" and _has_overdue_tasks(tasks):
            placeholder = f"{placeholder} ★"
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
        await _followup_with_bound_view(
            interaction,
            _render_active_task_selection(title, task, supplies=self.kind == "supplies"),
            view=BrainActiveTaskActionsView(
                self.parent_view.governor_tools,
                int(interaction.user.id),
                self.parent_view.request_for_kind(self.kind),
                task,
            ),
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


class EventCreateConfirmationView(BrainAutoClosingView):
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


class MemoCreateConfirmationView(BrainAutoClosingView):
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


class MemoDeleteConfirmationView(BrainAutoClosingView):
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


class MemoEditConfirmationView(BrainAutoClosingView):
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


class DocumentTagConfirmationView(BrainAutoClosingView):
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
