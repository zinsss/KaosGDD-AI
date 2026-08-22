from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
import re


class ToolKind(StrEnum):
    TODAY = "today"
    UPCOMING_EVENTS = "upcoming_events"
    CALENDAR_MONTH_IMAGE = "calendar_month_image"
    RECENT_IMPORTS = "recent_imports"
    ACTIVE_TASKS = "active_tasks"
    COMPLETED_TASKS = "completed_tasks"
    MEMO_SEARCH = "memo_search"
    DOCUMENT_SEARCH = "document_search"
    SEARCH_ALL = "search_all"


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
    if _looks_like_mutation(lowered):
        return None
    current = today or date.today()
    profile, collection_id = _scope(text, lowered)
    dotdot = _dotdot_request(text)
    if dotdot is not None:
        return dotdot
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


def _dotdot_request(text: str) -> ToolRequest | None:
    if not text.startswith(".."):
        return None
    query = " ".join(text[2:].strip().split())
    if not query:
        return None
    lowered = query.lower()
    document_nouns = ("document", "documents", "paperless", "페이퍼리스", "문서", "서류")
    memo_nouns = ("memo", "memos", "메모")
    if any(marker in lowered for marker in document_nouns):
        return ToolRequest(ToolKind.DOCUMENT_SEARCH, _strip_search_nouns(query, document_nouns) or query)
    if any(marker in lowered for marker in memo_nouns):
        return ToolRequest(ToolKind.MEMO_SEARCH, _strip_search_nouns(query, memo_nouns) or query)
    return ToolRequest(ToolKind.SEARCH_ALL, query)


def _asks_today(lowered: str) -> bool:
    return (
        ("오늘" in lowered and any(word in lowered for word in ("뭐", "일정", "스케줄", "있", "agenda", "calendar")))
        or ("오늘" in lowered and any(word in lowered for word in ("할 일", "할일", "해야", "todo", "task")))
        or any(phrase in lowered for phrase in ("오늘 일정", "오늘 스케줄", "오늘 캘린더"))
        or lowered in {"today", "today?", "agenda", "agenda?"}
        or lowered.startswith("what's on today")
        or lowered.startswith("whats on today")
    )


def _asks_active_tasks(lowered: str) -> bool:
    return (
        "뭐 해야" in lowered
        or "뭘 해야" in lowered
        or "해야 돼" in lowered
        or "해야되" in lowered
        or "해야하지" in lowered
        or "남은 할" in lowered
        or "열린 할" in lowered
        or "활성 할" in lowered
        or "할 일" in lowered
        or "할일" in lowered
        or "active task" in lowered
        or "open task" in lowered
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
    if not any(marker in lowered for marker in ("할 일", "할일", "task", "todo", "비품", "준비물", "용품", "supplies", "supply")):
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


def _looks_like_mutation(lowered: str) -> bool:
    if lowered.startswith(".."):
        return False
    if any(marker in lowered for marker in ("보여", "찾", "검색", "목록", "리스트", "알려", "뭐", "what", "show", "find", "search", "list")):
        return False
    return any(
        marker in lowered
        for marker in (
            "추가",
            "등록",
            "저장",
            "삭제",
            "지워",
            "없애",
            "완료",
            "끝냈",
            "끝내",
            "처리",
            "다시 살려",
            "되돌려",
            "수정",
            "편집",
            "변경",
            "바꿔",
        )
    )


def _scope(text: str, lowered: str) -> tuple[str, str]:
    if _asks_supplies(lowered):
        return "supplies", ""
    if "가족" in text or "family" in lowered:
        return "family", ""
    return "", ""


def _asks_supplies(lowered: str) -> bool:
    return any(marker in lowered for marker in ("비품", "준비물", "용품", "supplies", "supply"))


def _strip_scope_words(value: str) -> str:
    query = value
    for marker in ("가족", "family", "비품", "준비물", "용품", "supplies", "supply"):
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


def _strip_search_nouns(text: str, nouns: tuple[str, ...]) -> str:
    query = text
    for noun in sorted(nouns, key=len, reverse=True):
        query = re.sub(rf"\b{re.escape(noun)}\b", " ", query, flags=re.IGNORECASE)
        query = query.replace(f"{noun}에서", " ")
        query = query.replace(f"{noun}을", " ")
        query = query.replace(f"{noun}를", " ")
    return " ".join(query.split())
