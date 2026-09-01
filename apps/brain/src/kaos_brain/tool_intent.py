from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
import re


WEATHER_CITY_ALIASES = {
    "포항": ("pohang", "포항"),
    "pohang": ("pohang", "포항"),
    "대구": ("daegu", "대구"),
    "daegu": ("daegu", "대구"),
    "서울": ("seoul", "서울"),
    "seoul": ("seoul", "서울"),
    "부산": ("busan", "부산"),
    "busan": ("busan", "부산"),
    "울산": ("ulsan", "울산"),
    "ulsan": ("ulsan", "울산"),
    "경주": ("gyeongju", "경주"),
    "gyeongju": ("gyeongju", "경주"),
    "영천": ("yeongcheon", "영천"),
    "yeongcheon": ("yeongcheon", "영천"),
    "영해": ("yeonghae", "영해"),
    "yeonghae": ("yeonghae", "영해"),
    "영덕": ("yeongdeok", "영덕"),
    "yeongdeok": ("yeongdeok", "영덕"),
    "제주": ("jeju", "제주"),
    "jeju": ("jeju", "제주"),
    "인천": ("incheon", "인천"),
    "incheon": ("incheon", "인천"),
    "대전": ("daejeon", "대전"),
    "daejeon": ("daejeon", "대전"),
    "광주": ("gwangju", "광주"),
    "gwangju": ("gwangju", "광주"),
    "도쿄": ("tokyo", "도쿄"),
    "tokyo": ("tokyo", "도쿄"),
    "동경": ("tokyo", "도쿄"),
    "오사카": ("osaka", "오사카"),
    "osaka": ("osaka", "오사카"),
    "후쿠오카": ("fukuoka", "후쿠오카"),
    "fukuoka": ("fukuoka", "후쿠오카"),
    "방콕": ("bangkok", "방콕"),
    "bangkok": ("bangkok", "방콕"),
    "싱가포르": ("singapore", "싱가포르"),
    "singapore": ("singapore", "싱가포르"),
    "타이베이": ("taipei", "타이베이"),
    "타이페이": ("taipei", "타이베이"),
    "taipei": ("taipei", "타이베이"),
    "홍콩": ("hongkong", "홍콩"),
    "hongkong": ("hongkong", "홍콩"),
    "hong kong": ("hongkong", "홍콩"),
    "런던": ("london", "런던"),
    "london": ("london", "런던"),
    "파리": ("paris", "파리"),
    "paris": ("paris", "파리"),
    "뉴욕": ("newyork", "뉴욕"),
    "newyork": ("newyork", "뉴욕"),
    "new york": ("newyork", "뉴욕"),
    "엘에이": ("losangeles", "LA"),
    "la": ("losangeles", "LA"),
    "losangeles": ("losangeles", "LA"),
    "los angeles": ("losangeles", "LA"),
    "시애틀": ("seattle", "시애틀"),
    "seattle": ("seattle", "시애틀"),
    "호놀룰루": ("honolulu", "호놀룰루"),
    "honolulu": ("honolulu", "호놀룰루"),
    "시드니": ("sydney", "시드니"),
    "sydney": ("sydney", "시드니"),
}
DEFAULT_LOCATION_WORDS = {"", "여기", "현재위치", "currentlocation", "here"}


class ToolKind(StrEnum):
    TODAY = "today"
    WEATHER = "weather"
    UPCOMING_EVENTS = "upcoming_events"
    CALENDAR_MONTH_IMAGE = "calendar_month_image"
    RECENT_IMPORTS = "recent_imports"
    MAIL_MESSAGES = "mail_messages"
    SYSTEM_STATUS = "system_status"
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
    text = " ".join(_normalize_date_separators(content).strip().split())
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
    day_request = _specific_day_request(text, lowered, current, profile=profile)
    if day_request is not None:
        return day_request
    if _asks_weather(lowered):
        label, city = _weather_location(text)
        return ToolRequest(ToolKind.WEATHER, label, start=current.isoformat(), profile=profile, collection_id=city)
    if _asks_today(lowered):
        return ToolRequest(ToolKind.TODAY, start=current.isoformat(), profile=profile)
    if _asks_system_status(lowered):
        return ToolRequest(ToolKind.SYSTEM_STATUS, profile=profile)
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
    document_nouns = ("document", "documents", "paperless", "페이퍼리스", "문서", "서류")
    memo_nouns = ("memo", "memos", "메모")
    stripped_query = _strip_search_nouns(query, (*document_nouns, *memo_nouns)) or query
    return ToolRequest(ToolKind.SEARCH_ALL, stripped_query)


def _specific_day_request(text: str, lowered: str, today: date, *, profile: str) -> ToolRequest | None:
    cleaned = lowered
    for marker in (
        "보여줘",
        "보여",
        "알려줘",
        "알려",
        "일정",
        "스케줄",
        "캘린더",
        "calendar",
        "show",
        "?",
    ):
        cleaned = cleaned.replace(marker, " ")
    cleaned = " ".join(cleaned.split())
    if cleaned in {"오늘", "today"}:
        return ToolRequest(ToolKind.TODAY, start=today.isoformat(), profile=profile)
    if cleaned in {"내일", "tomorrow"}:
        return ToolRequest(ToolKind.TODAY, start=(today + timedelta(days=1)).isoformat(), profile=profile)
    if cleaned in {"모레"}:
        return ToolRequest(ToolKind.TODAY, start=(today + timedelta(days=2)).isoformat(), profile=profile)

    parsed = _parse_explicit_day(cleaned, today=today)
    if parsed is None:
        return None
    return ToolRequest(ToolKind.TODAY, start=parsed.isoformat(), profile=profile)


def _parse_explicit_day(cleaned: str, *, today: date) -> date | None:
    match = re.fullmatch(r"(?:(\d{4})[./-])?(\d{1,2})[./-](\d{1,2})", cleaned)
    if match is None:
        match = re.fullmatch(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일?", cleaned)
    if match is None:
        return None
    year_text, month_text, day_text = match.groups()
    year = int(year_text) if year_text else today.year
    month = int(month_text)
    day = int(day_text)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _normalize_date_separators(value: str) -> str:
    return value.replace("／", "/").replace("．", ".").replace("－", "-").replace("–", "-").replace("—", "-")


def _asks_today(lowered: str) -> bool:
    return (
        ("오늘" in lowered and any(word in lowered for word in ("뭐", "일정", "스케줄", "있", "agenda", "calendar")))
        or ("오늘" in lowered and any(word in lowered for word in ("할 일", "할일", "해야", "todo", "task")))
        or any(phrase in lowered for phrase in ("오늘 일정", "오늘 스케줄", "오늘 캘린더"))
        or lowered in {"today", "today?", "agenda", "agenda?"}
        or lowered.startswith("what's on today")
        or lowered.startswith("whats on today")
    )


def _asks_weather(lowered: str) -> bool:
    return (
        "날씨" in lowered
        or "weather" in lowered
        or "temperature" in lowered
        or "기온" in lowered
    )


def _weather_location_label(text: str) -> str:
    cleaned = text
    for marker in ("지금", "현재", "오늘", "날씨", "는", "은", "이", "가", "?", "알려줘", "보여줘"):
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"\b(weather|temperature|current|today|now|show|tell|me)\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _weather_location(text: str) -> tuple[str, str]:
    label = _weather_location_label(text)
    normalized = label.lower().replace(" ", "")
    if normalized in DEFAULT_LOCATION_WORDS:
        return "", ""
    for alias, (city, display) in WEATHER_CITY_ALIASES.items():
        if alias.lower().replace(" ", "") == normalized:
            return display, city
    return label, f"unsupported:{label}" if label else ""


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


def _asks_system_status(lowered: str) -> bool:
    return (
        any(marker in lowered for marker in ("system status", "service status", "server status", "health check"))
        or ("시스템" in lowered and any(marker in lowered for marker in ("상태", "점검", "확인", "헬스", "헬스체크")))
        or ("서버" in lowered and any(marker in lowered for marker in ("상태", "점검", "확인", "헬스", "헬스체크")))
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
            "만들어",
            "생성",
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
