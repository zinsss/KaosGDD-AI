from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re


KOREAN_WEEKDAYS = {
    "월요일": 0,
    "월": 0,
    "화요일": 1,
    "화": 1,
    "수요일": 2,
    "수": 2,
    "목요일": 3,
    "목": 3,
    "금요일": 4,
    "금": 4,
    "토요일": 5,
    "토": 5,
    "일요일": 6,
    "일": 6,
}


@dataclass(frozen=True)
class TaskDueUpdateRequest:
    task_title: str
    due_date: str
    due_time: str = "10:00"
    profile: str = ""
    collection_id: str = ""


@dataclass(frozen=True)
class TaskCreateRequest:
    title: str
    due_date: str
    due_time: str = "10:00"
    profile: str = ""
    collection_id: str = ""


@dataclass(frozen=True)
class TaskActionRequest:
    task_title: str
    action: str
    profile: str = ""
    collection_id: str = ""


@dataclass(frozen=True)
class TaskTextEditRequest:
    task_title: str
    title: str
    memo: str = ""
    due_date: str = ""
    due_time: str = ""
    priority: str = ""
    profile: str = ""
    collection_id: str = ""


def parse_task_due_update(content: str, *, today: date) -> TaskDueUpdateRequest | None:
    text = " ".join(content.strip().split())
    if not text or not any(marker in text for marker in ("편집", "변경", "바꿔", "수정")):
        return None
    profile, collection_id = _scope(text)
    parsed = _extract_due_date(text, today=today)
    if parsed is None:
        return None
    phrase, due_date = parsed
    due_time = _extract_due_time(text) or "10:00"
    title = text.split(phrase, 1)[0]
    title = _clean_title(_strip_scope_words(title))
    if not title:
        return None
    return TaskDueUpdateRequest(task_title=title, due_date=due_date.isoformat(), due_time=due_time, profile=profile, collection_id=collection_id)


def parse_task_edit(content: str) -> TaskTextEditRequest | None:
    text = " ".join(content.strip().split())
    if not text or not any(marker in text for marker in ("편집", "변경", "바꿔", "수정")):
        return None
    profile, collection_id = _scope(text)
    title_match = re.match(r"(.+?)\s+(?:제목|이름)[을를]?\s+(.+?)(?:으?로)?\s*(?:편집|변경|바꿔줘|바꿔|수정)\s*$", text)
    if title_match:
        task_title = _clean_title(_strip_scope_words(title_match.group(1)))
        new_title = _clean_action_title(_strip_scope_words(title_match.group(2)))
        if task_title and new_title:
            return TaskTextEditRequest(task_title=task_title, title=new_title, profile=profile, collection_id=collection_id)
    memo_match = re.match(r"(.+?)\s+(?:메모|내용)[을를]?\s+(.+?)(?:으?로)?\s*(?:편집|변경|바꿔줘|바꿔|수정)\s*$", text)
    if memo_match:
        task_title = _clean_title(_strip_scope_words(memo_match.group(1)))
        memo = memo_match.group(2).strip(" .,")
        if task_title and memo:
            return TaskTextEditRequest(task_title=task_title, title=task_title, memo=memo, profile=profile, collection_id=collection_id)
    return None


def parse_task_create(content: str, *, today: date) -> TaskCreateRequest | None:
    text = " ".join(content.strip().split())
    if not text or any(marker in text for marker in ("편집", "변경", "바꿔", "수정")):
        return None
    supplies_request = _is_supplies(text)
    if supplies_request:
        supplies_create = _parse_supplies_create(text)
        if supplies_create is not None:
            return supplies_create
    explicit_create = _parse_explicit_task_create(text)
    if explicit_create is not None:
        return explicit_create
    if not any(marker in text for marker in ("해야", "할 일", "해야돼", "해야되", "해야 해", "필요")):
        return None
    profile, collection_id = _scope(text)
    parsed = _extract_due_date(text, today=today)
    if parsed is None:
        return None
    phrase, due_date = parsed
    due_time = _extract_due_time(text) or "10:00"
    title = text.replace(phrase, " ", 1)
    title = _remove_time_phrase(title)
    title = re.sub(r"(까지로|까지는|까지)", " ", title, count=1)
    title = _clean_create_title(_strip_scope_words(title))
    if not title:
        return None
    return TaskCreateRequest(title=title, due_date=due_date.isoformat(), due_time=due_time, profile=profile, collection_id=collection_id)


def parse_task_action(content: str) -> TaskActionRequest | None:
    text = " ".join(content.strip().split())
    if not text:
        return None
    profile, collection_id = _scope(text)
    delete_marker = _first_marker(text, ("삭제해줘", "삭제", "지워줘", "지워", "없애줘", "없애"))
    if delete_marker is not None:
        title = _clean_action_title(_strip_scope_words(text.replace(delete_marker, " ", 1)))
        return TaskActionRequest(task_title=title, action="delete", profile=profile, collection_id=collection_id) if title else None
    reopen_marker = _first_marker(text, ("완료 취소", "완료취소", "다시 살려줘", "다시 살려", "살려줘", "살려", "되돌려줘", "되돌려", "undo"))
    if reopen_marker is not None:
        title = _clean_action_title(_strip_scope_words(text.replace(reopen_marker, " ", 1)))
        return TaskActionRequest(task_title=title, action="reopen", profile=profile, collection_id=collection_id) if title else None
    complete_marker = _first_marker(text, ("완료", "끝냈어", "끝냈다", "끝냄", "끝내줘", "끝내", "처리했어", "처리"))
    if complete_marker is not None:
        title = _clean_action_title(_strip_scope_words(text.replace(complete_marker, " ", 1)))
        return TaskActionRequest(task_title=title, action="complete", profile=profile, collection_id=collection_id) if title else None
    return None


def _extract_due_date(text: str, *, today: date) -> tuple[str, date] | None:
    iso_match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", text)
    if iso_match:
        try:
            return iso_match.group(1), date.fromisoformat(iso_match.group(1))
        except ValueError:
            return None
    month_day_match = re.search(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)", text)
    if month_day_match:
        return _date_from_month_day(month_day_match.group(0), int(month_day_match.group(1)), int(month_day_match.group(2)), today=today)
    korean_month_day_match = re.search(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if korean_month_day_match:
        return _date_from_month_day(
            korean_month_day_match.group(0),
            int(korean_month_day_match.group(1)),
            int(korean_month_day_match.group(2)),
            today=today,
        )
    if "오늘" in text:
        return "오늘", today
    if "내일" in text:
        return "내일", today + timedelta(days=1)
    if "모레" in text:
        return "모레", today + timedelta(days=2)
    for name, weekday in KOREAN_WEEKDAYS.items():
        phrase = f"다음주 {name}"
        if phrase in text:
            return phrase, _next_weekday(today, weekday)
    return None


def _date_from_month_day(phrase: str, month: int, day: int, *, today: date) -> tuple[str, date] | None:
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate < today:
        try:
            candidate = date(today.year + 1, month, day)
        except ValueError:
            return None
    return phrase, candidate


def _extract_due_time(text: str) -> str | None:
    clock_match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if clock_match:
        return f"{int(clock_match.group(1)):02d}:{clock_match.group(2)}"
    korean_match = re.search(r"(오전|오후)\s*(\d{1,2})\s*시\s*(반)?", text)
    if not korean_match:
        return None
    hour = int(korean_match.group(2))
    if hour < 1 or hour > 12:
        return None
    if korean_match.group(1) == "오후" and hour != 12:
        hour += 12
    if korean_match.group(1) == "오전" and hour == 12:
        hour = 0
    minute = 30 if korean_match.group(3) else 0
    return f"{hour:02d}:{minute:02d}"


def _remove_time_phrase(text: str) -> str:
    text = re.sub(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", " ", text, count=1)
    return re.sub(r"(오전|오후)\s*\d{1,2}\s*시\s*반?", " ", text, count=1)


def _next_weekday(today: date, weekday: int) -> date:
    days_until = (weekday - today.weekday()) % 7
    return today + timedelta(days=days_until + 7 if days_until == 0 else days_until)


def _clean_title(value: str) -> str:
    title = value.strip(" .,")
    for suffix in ("마감일을", "마감일", "기한을", "기한", "due date", "due"):
        title = title.removesuffix(suffix).strip(" .,")
    return title


def _clean_create_title(value: str) -> str:
    title = value.strip(" .,")
    for suffix in ("해야돼", "해야되", "해야 해", "해야", "할 일", "필요"):
        title = title.removesuffix(suffix).strip(" .,")
    for prefix in ("까지", "까지로", "까지는"):
        title = title.removeprefix(prefix).strip(" .,")
    return title


def _first_marker(text: str, markers: tuple[str, ...]) -> str | None:
    matches = [(text.find(marker), marker) for marker in markers if marker in text]
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def _clean_action_title(value: str) -> str:
    title = value.strip(" .,")
    for suffix in ("해줘", "해", "줘"):
        title = title.removesuffix(suffix).strip(" .,")
    for suffix in ("task", "태스크", "할 일", "할일"):
        title = title.removesuffix(suffix).strip(" .,")
    return title


def _scope(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if _is_supplies(text):
        return "supplies", ""
    if "가족" in text or "family" in lowered:
        return "family", ""
    return "", ""


def _parse_supplies_create(text: str) -> TaskCreateRequest | None:
    marker = _first_marker(text, ("추가해줘", "추가", "저장해줘", "저장", "등록해줘", "등록"))
    if marker is None:
        return None
    title = _strip_scope_words(text.replace(marker, " ", 1))
    title = _clean_action_title(title)
    if not title:
        return None
    return TaskCreateRequest(title=title, due_date="", due_time="", profile="supplies")


def _parse_explicit_task_create(text: str) -> TaskCreateRequest | None:
    if not any(marker in text for marker in ("할 일", "할일", "task", "태스크")):
        return None
    marker = _first_marker(text, ("추가해줘", "추가", "저장해줘", "저장", "등록해줘", "등록"))
    if marker is None:
        return None
    profile, collection_id = _scope(text)
    title = _strip_scope_words(text.replace(marker, " ", 1))
    title = re.sub(r"(할\s*일|할일|task|태스크)", " ", title, flags=re.IGNORECASE)
    title = _clean_action_title(title)
    if not title:
        return None
    return TaskCreateRequest(title=title, due_date="", due_time="", profile=profile, collection_id=collection_id)


def _is_supplies(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("준비물", "용품", "supplies", "supply"))


def _strip_scope_words(value: str) -> str:
    result = value
    for marker in ("가족", "family", "준비물", "용품", "supplies", "supply"):
        result = re.sub(rf"\b{re.escape(marker)}\b", " ", result, flags=re.IGNORECASE)
        result = result.replace(marker, " ")
    return result
