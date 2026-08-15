from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
import re


class ToolKind(StrEnum):
    TODAY = "today"
    ACTIVE_TASKS = "active_tasks"
    COMPLETED_TASKS = "completed_tasks"
    MEMO_SEARCH = "memo_search"
    DOCUMENT_SEARCH = "document_search"


@dataclass(frozen=True)
class ToolRequest:
    kind: ToolKind
    query: str = ""
    start: str = ""
    end: str = ""
    profile: str = ""
    collection_id: str = ""


def parse_tool_request(content: str, *, today: date | None = None) -> ToolRequest | None:
    text = " ".join(content.strip().split())
    lowered = text.lower()
    if not text:
        return None
    current = today or date.today()
    profile, collection_id = _scope(text, lowered)
    if _asks_today(lowered):
        return ToolRequest(ToolKind.TODAY, profile=profile)
    completed = _completed_task_request(text, lowered, current, profile=profile, collection_id=collection_id)
    if completed is not None:
        return completed
    if _asks_active_tasks(lowered) or _asks_supplies(lowered):
        return ToolRequest(ToolKind.ACTIVE_TASKS, profile=profile, collection_id=collection_id)
    memo_query = _search_query(text, ("memo", "memos", "메모"))
    if memo_query:
        return ToolRequest(ToolKind.MEMO_SEARCH, memo_query)
    document_query = _search_query(text, ("document", "documents", "paperless", "문서", "서류"))
    if document_query:
        return ToolRequest(ToolKind.DOCUMENT_SEARCH, document_query)
    return None


def _asks_today(lowered: str) -> bool:
    return (
        ("오늘" in lowered and any(word in lowered for word in ("뭐", "일정", "있", "agenda")))
        or lowered in {"today", "today?", "agenda", "agenda?"}
        or lowered.startswith("what's on today")
        or lowered.startswith("whats on today")
    )


def _asks_active_tasks(lowered: str) -> bool:
    return (
        "뭐 해야" in lowered
        or "해야 돼" in lowered
        or "해야되" in lowered
        or "할 일" in lowered
        or "할일" in lowered
        or "active task" in lowered
        or "todo" in lowered
    )


def _completed_task_request(
    text: str,
    lowered: str,
    today: date,
    *,
    profile: str,
    collection_id: str,
) -> ToolRequest | None:
    if "완료" not in lowered:
        return None
    if not any(marker in lowered for marker in ("할 일", "할일", "task", "todo", "준비물", "용품", "supplies", "supply")):
        return None
    days = 14 if any(marker in lowered for marker in ("최근 2주", "지난 2주", "2주")) else 30
    query = _strip_scope_words(text)
    for marker in (
        "최근 2주",
        "지난 2주",
        "2주",
        "최근 한달",
        "지난 한달",
        "한달",
        "완료된",
        "완료",
        "할 일",
        "할일",
        "목록",
        "리스트",
        "보여줘",
        "보여",
        "찾아줘",
        "찾아",
        "검색해줘",
        "검색",
    ):
        query = query.replace(marker, " ")
    query = re.sub(r"\b(completed|complete|done|tasks?|todos?|list|show|find|search|recent)\b", " ", query, flags=re.IGNORECASE)
    return ToolRequest(
        ToolKind.COMPLETED_TASKS,
        " ".join(query.split()),
        (today - timedelta(days=days - 1)).isoformat(),
        today.isoformat(),
        profile,
        collection_id,
    )


def _scope(text: str, lowered: str) -> tuple[str, str]:
    if _asks_supplies(lowered):
        return "supplies", ""
    if "가족" in text or "family" in lowered:
        return "family", ""
    return "", ""


def _asks_supplies(lowered: str) -> bool:
    return any(marker in lowered for marker in ("준비물", "용품", "supplies", "supply"))


def _strip_scope_words(value: str) -> str:
    query = value
    for marker in ("가족", "family", "준비물", "용품", "supplies", "supply"):
        query = re.sub(rf"\b{re.escape(marker)}\b", " ", query, flags=re.IGNORECASE)
        query = query.replace(marker, " ")
    return query


def _search_query(text: str, nouns: tuple[str, ...]) -> str:
    lowered = text.lower()
    if not any(noun in lowered for noun in nouns):
        return ""
    if not any(marker in lowered for marker in ("찾", "검색", "보여", "관련", "search", "find", "show")):
        return ""
    query = text
    for noun in sorted(nouns, key=len, reverse=True):
        query = re.sub(rf"\b{re.escape(noun)}\b", " ", query, flags=re.IGNORECASE)
        query = query.replace(f"{noun}에서", " ")
        query = query.replace(f"{noun}을", " ")
        query = query.replace(f"{noun}를", " ")
    query = re.sub(r"\b(search|find|show)\b", " ", query, flags=re.IGNORECASE)
    for marker in ("찾아줘", "찾아", "찾", "검색해줘", "검색해", "검색", "보여줘", "보여", "관련"):
        query = query.replace(marker, " ")
    return " ".join(query.split())
