from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class ToolKind(StrEnum):
    TODAY = "today"
    ACTIVE_TASKS = "active_tasks"
    MEMO_SEARCH = "memo_search"
    DOCUMENT_SEARCH = "document_search"


@dataclass(frozen=True)
class ToolRequest:
    kind: ToolKind
    query: str = ""


def parse_tool_request(content: str) -> ToolRequest | None:
    text = " ".join(content.strip().split())
    lowered = text.lower()
    if not text:
        return None
    if _asks_today(lowered):
        return ToolRequest(ToolKind.TODAY)
    if _asks_active_tasks(lowered):
        return ToolRequest(ToolKind.ACTIVE_TASKS)
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


def _search_query(text: str, nouns: tuple[str, ...]) -> str:
    lowered = text.lower()
    if not any(noun in lowered for noun in nouns):
        return ""
    if not any(marker in lowered for marker in ("찾", "검색", "search", "find")):
        return ""
    query = text
    for noun in sorted(nouns, key=len, reverse=True):
        query = re.sub(rf"\b{re.escape(noun)}\b", " ", query, flags=re.IGNORECASE)
        query = query.replace(f"{noun}에서", " ")
        query = query.replace(f"{noun}을", " ")
        query = query.replace(f"{noun}를", " ")
    query = re.sub(r"\b(search|find)\b", " ", query, flags=re.IGNORECASE)
    for marker in ("찾아줘", "찾아", "찾", "검색해줘", "검색해", "검색"):
        query = query.replace(marker, " ")
    return " ".join(query.split())
