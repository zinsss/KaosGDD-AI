from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, time as datetime_time, timedelta
import io
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

import discord

from .governor_tools import (
    FAMILY_EVENT_MARKER,
    FAMILY_EVENT_SUFFIX,
    GovernorToolClient,
    GovernorToolError,
    PERSONAL_EVENT_MARKER,
    SEARCH_RESULT_LIMIT,
    document_option_label,
    memo_option_label,
)
from .list_formatting import page_window, range_summary as _range_summary
from .tool_intent import ToolRequest

LOGGER = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

ACTIVE_CONTROL_MARKER = "# "
SERVICE_MENU_MARKER = "### KaosGDD Services"
ACTIVE_CONTROL_LIMIT = 10
ACTIVE_CONTROL_HISTORY_LIMIT = 20
TASK_SERVICE_PAGE_SIZE = 10
TASK_SERVICE_HISTORY_LIMIT = 250
FAX_MAIL_PAGE_SIZE = 10
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
FAX_MAIL_TITLE = "𝓕𝓪𝔁 𝓜𝓪𝓲𝓵"
KOREAN_SHORT_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


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


def render_active_control_message(
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    supplies: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(KST)
    return f"# {current:%Y.%m.%d}({current:%a})"


def _task_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tasks")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _event_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("events")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _import_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("imports")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _fax_mail_results(payload: dict[str, Any], *, mode: str) -> list[dict[str, Any]]:
    imports = _import_results(payload)
    if mode == "outgoing":
        return [item for item in imports if _import_kind(item) == "fax" and _import_direction(item) == "outgoing"]
    return [
        item
        for item in imports
        if _import_kind(item) == "fax" and _import_direction(item) != "outgoing" and not _import_is_user_checked(item)
    ]


def _active_fax_mail_imports(imports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in imports if _is_active_fax_mail_import(item)]


def _is_active_fax_mail_import(item: dict[str, Any]) -> bool:
    kind = _import_kind(item)
    direction = _import_direction(item)
    if kind not in {"fax", "mail"} or direction != "incoming":
        return False
    return not _import_is_user_checked(item)


def _import_is_user_checked(item: dict[str, Any]) -> bool:
    for key in ("checked", "read", "seen", "handled", "dismissed"):
        value = item.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}:
            return True
    state = str(item.get("userState") or item.get("user_state") or "").strip().lower()
    return state in {"checked", "read", "seen", "handled", "dismissed"}


def _mail_message_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("messages")
    messages = [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    return sorted(messages, key=_mail_sort_key, reverse=True)


def _mail_sort_key(item: dict[str, Any]) -> str:
    return str(item.get("receivedAt") or item.get("date") or item.get("createdAt") or "")


async def _active_control_month_file_for(
    governor_tools: GovernorToolClient | None,
    *,
    profile: str,
    year: int | None = None,
    month: int | None = None,
    today: object | None = None,
) -> discord.File | None:
    if governor_tools is None:
        return None
    try:
        payload = await governor_tools.calendar_month_image(profile=profile, year=year, month=month, today=today)
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


def _render_fax_mail_selection(item: dict[str, Any]) -> str:
    if _import_kind(item) != "mail":
        return _render_import_selection(item)
    title = str(item.get("subject") or item.get("title") or "(No subject)").strip() or "(No subject)"
    sender = str(item.get("sender") or "").strip()
    mailbox = str(item.get("mailbox") or "").strip()
    received = str(item.get("receivedAt") or "").strip()
    preview = str(item.get("preview") or "").strip()
    lines = [f"## {_safe_discord_line(title)}"]
    for label, value in (("date", received), ("from", sender), ("folder", mailbox)):
        if value:
            lines.append(f"- {label}: {_safe_discord_line(value)}")
    if preview:
        lines.append("")
        lines.append(_safe_discord_line(preview)[:1000])
    return "\n".join(lines)[:1900]


def _render_memo_list_message(
    query: str,
    results: list[dict[str, Any]],
    *,
    result_count: int,
    total_count: int,
    searched: bool = False,
) -> str:
    start = 1 if results else 0
    display_title = MEMOS_TITLE if not query.strip() else query.strip()
    lines = []
    if searched:
        lines.append("Searched..")
    lines.extend([
        f"## {display_title}",
        _range_summary(start, len(results), result_count),
    ])
    if query.strip() or searched:
        lines.append(f"{result_count} results in {total_count} memos")
    lines.append("")
    for item in results[:SEARCH_RESULT_LIMIT]:
        lines.append(f"- {_safe_discord_line(memo_option_label(item))}")
    if not results:
        lines.append("- No matching memos.")
    return "\n".join(lines)[:1900]


def _render_document_list_message(
    query: str,
    results: list[dict[str, Any]],
    *,
    result_count: int,
    total_count: int,
    page: int,
    page_size: int,
    searched: bool = False,
) -> str:
    start = (max(1, page) - 1) * max(1, page_size) + 1 if results else 0
    display_title = PAPERLESS_TITLE if not query.strip() else query.strip()
    lines = []
    if searched:
        lines.append("Searched..")
    lines.extend([
        f"## {display_title}",
        _range_summary(start, len(results), result_count),
    ])
    if query.strip() or searched:
        lines.append(f"{result_count} results in {total_count} documents")
    lines.append("")
    for item in results[:page_size]:
        lines.append(f"- {_safe_discord_line(document_option_label(item))}")
    if not results:
        lines.append("- No matching documents.")
    return "\n".join(lines)[:1900]


def _render_fax_mail_service_message(imports: list[dict[str, Any]], *, mode: str, page: int) -> str:
    window = page_window(imports, page=page, page_size=FAX_MAIL_PAGE_SIZE)
    subtitle = _fax_mail_mode_label(mode)
    empty = {"incoming_fax": "no incoming fax", "outgoing_fax": "no outgoing fax", "mail": "no target mail"}.get(mode, "no items")
    lines = [f"## {FAX_MAIL_TITLE}", f"### {subtitle}", window.range_label, ""]
    for item in window.items:
        lines.append(f"- {_fax_mail_list_line(item)}")
    if not window.items:
        lines.append(f"- {empty}")
    return "\n".join(lines)


def _fax_mail_mode_label(mode: str) -> str:
    return {
        "incoming_fax": "Incoming Fax",
        "outgoing_fax": "Outgoing Fax",
        "mail": "Mail",
    }.get(mode, "Incoming Fax")


def _fax_mail_option_label(item: dict[str, Any]) -> str:
    if _import_kind(item) == "mail":
        return _compact_select_text(_fax_mail_mail_heading(item, escape=False), 100)
    return _compact_select_text(str(item.get("subject") or item.get("title") or "Import"), 100)


def _fax_mail_option_description(item: dict[str, Any]) -> str:
    if _import_kind(item) == "mail":
        return _compact_select_text(f"{_mail_attachment_summary(item)} from {_mail_sender_display(item)}", 100)
    return _import_option_description(item)


def _fax_mail_list_line(item: dict[str, Any]) -> str:
    if _import_kind(item) == "mail":
        return _fax_mail_mail_heading(item, escape=True)
    title = _safe_discord_line(str(item.get("subject") or item.get("title") or "Import").strip() or "Import")
    detail = _safe_discord_line(str(item.get("detail") or "").strip())
    return f"{title} · {detail}" if detail else title


def _fax_mail_mail_heading(item: dict[str, Any], *, escape: bool) -> str:
    title = str(item.get("subject") or item.get("title") or "(No subject)").strip() or "(No subject)"
    received = _mail_mmdd(str(item.get("receivedAt") or ""))
    mailbox = str(item.get("mailbox") or "").strip()
    heading = f"{title}{f'({received})' if received else ''}"
    if mailbox:
        heading = f"{heading} • <{mailbox}>"
    return _safe_discord_line(heading) if escape else heading


def _mail_mmdd(value: str) -> str:
    match = re.search(r"\b\d{4}-(\d{2})-(\d{2})\b", value)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def _mail_attachment_summary(item: dict[str, Any]) -> str:
    names = item.get("attachmentNames") or item.get("attachments")
    if isinstance(names, list):
        cleaned = [str(value).strip() for value in names if str(value).strip()]
        if cleaned:
            return ", ".join(cleaned[:2]) + (f" 외 {len(cleaned) - 2}개" if len(cleaned) > 2 else "")
    try:
        count = int(item.get("attachmentCount") or 0)
    except (TypeError, ValueError):
        count = 0
    return f"첨부 {count}개" if count else "첨부 없음"


def _mail_sender_display(item: dict[str, Any]) -> str:
    sender = str(item.get("sender") or "").strip()
    if not sender:
        return "unknown"
    if "<" in sender:
        sender = sender.split("<", 1)[0].strip()
    return sender.strip('"') or str(item.get("sender") or "").strip()


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
    window = page_window(tasks, page=page, page_size=TASK_SERVICE_PAGE_SIZE)
    if history:
        month_label = f"{month:%Y.%m}" if month else ""
        lines = [f"## {title}", f"### {month_label} • Completed: {len(tasks)}", window.range_label, ""]
    else:
        lines = [f"## {title}", window.range_label, ""]
    for task in window.items:
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
    if not window.items:
        lines.append("- none")
    return "\n".join(lines)


def _render_active_service_message(title: str, tasks: list[dict[str, Any]], *, supplies: bool = False) -> str:
    lines = [f"## {title}", f"- active: {len(tasks)}"]
    for task in tasks[:SEARCH_RESULT_LIMIT]:
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
    if len(tasks) > SEARCH_RESULT_LIMIT:
        lines.append(f"- {len(tasks) - SEARCH_RESULT_LIMIT} more")
    if not tasks:
        lines.append("- none")
    return "\n".join(lines)


async def _render_calendar_weekly(governor_tools: GovernorToolClient, *, profile: str, start: date) -> str:
    days = [start + timedelta(days=offset) for offset in range(7)]
    payload = await governor_tools.calendar_week(profile=profile, start=start.isoformat(), days=7)
    raw_items = payload.get("items")
    items = [dict(item) for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    payloads = {str(item.get("date") or ""): item for item in items}
    lines = [f"## {CALENDAR_TITLE} · 𝓦𝓮𝓮𝓴𝓵𝔂", f"< {days[0]:%Y.%m.%d} - {days[-1]:%Y.%m.%d} >"]
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


def _week_start_sunday(value: date) -> date:
    return value - timedelta(days=(value.weekday() + 1) % 7)


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


def _import_kind(item: dict[str, Any]) -> str:
    return str(item.get("kind") or "").strip().lower()


def _import_direction(item: dict[str, Any]) -> str:
    return str(item.get("direction") or "").strip().lower()


def _safe_discord_line(value: str) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value))


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


def _has_overdue_tasks(tasks: list[dict[str, Any]], *, now: datetime | None = None) -> bool:
    current = now or datetime.now(KST)
    return any(_is_overdue_task(task, now=current) for task in tasks)


def _is_overdue_task(task: dict[str, Any], *, now: datetime | None = None) -> bool:
    if str(task.get("status") or "").strip().upper() == "COMPLETED":
        return False
    due = str(task.get("due") or task.get("dueDate") or "").strip()
    if not due:
        return False
    try:
        due_date = date.fromisoformat(due[:10])
    except ValueError:
        return False
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    today = current.date()
    if due_date < today:
        return True
    if due_date > today:
        return False
    due_time = _parse_due_time(str(task.get("dueTime") or "").strip())
    if due_time is None:
        return False
    return datetime.combine(due_date, due_time, tzinfo=KST) <= current


def _parse_due_time(value: str) -> datetime_time | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:5], "%H:%M").time()
    except ValueError:
        return None


def _compact_select_text(value: str, limit: int) -> str:
    text = " ".join(value.split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
