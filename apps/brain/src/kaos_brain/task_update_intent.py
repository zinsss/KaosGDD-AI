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


def parse_task_due_update(content: str, *, today: date) -> TaskDueUpdateRequest | None:
    text = " ".join(content.strip().split())
    if not text or not any(marker in text for marker in ("편집", "변경", "바꿔", "수정")):
        return None
    parsed = _extract_due_date(text, today=today)
    if parsed is None:
        return None
    phrase, due_date = parsed
    title = text.split(phrase, 1)[0]
    title = _clean_title(title)
    if not title:
        return None
    return TaskDueUpdateRequest(task_title=title, due_date=due_date.isoformat())


def _extract_due_date(text: str, *, today: date) -> tuple[str, date] | None:
    iso_match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", text)
    if iso_match:
        try:
            return iso_match.group(1), date.fromisoformat(iso_match.group(1))
        except ValueError:
            return None
    if "내일" in text:
        return "내일", today + timedelta(days=1)
    for name, weekday in KOREAN_WEEKDAYS.items():
        phrase = f"다음주 {name}"
        if phrase in text:
            return phrase, _next_weekday(today, weekday)
    return None


def _next_weekday(today: date, weekday: int) -> date:
    days_until = (weekday - today.weekday()) % 7
    return today + timedelta(days=days_until + 7 if days_until == 0 else days_until)


def _clean_title(value: str) -> str:
    title = value.strip(" .,")
    for suffix in ("마감일을", "마감일", "기한을", "기한", "due date", "due"):
        title = title.removesuffix(suffix).strip(" .,")
    return title
