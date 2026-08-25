from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re


@dataclass(frozen=True)
class EventCreateRequest:
    title: str
    start_date: str
    end_date: str
    all_day: bool = True
    memo: str = ""
    profile: str = "main"


def parse_event_create(content: str, *, today: date) -> EventCreateRequest | None:
    text = " ".join(content.strip().split())
    prefixed_body = _prefixed_event_body(text)
    if prefixed_body:
        text = prefixed_body
    elif not text or "일정" not in text or "추가" not in text:
        return None
    date_match = re.search(r"(?<!\d)(?:(?P<year>\d{4})[-./])?(?P<month>\d{1,2})[-./](?P<day>\d{1,2})(?!\d)", text)
    relative_default_all_day = False
    if date_match is not None:
        year = int(date_match.group("year") or today.year)
        month = int(date_match.group("month"))
        day = int(date_match.group("day"))
        try:
            start = date(year, month, day)
        except ValueError:
            return None
        rest, memo = _split_inline_memo(text[date_match.end() :].strip(" .,"))
    else:
        relative = _relative_event_date(text, today=today)
        if relative is None:
            return None
        start, rest, memo = relative
        relative_default_all_day = True
    memo_match = re.search(r"(?:메모|memo)\s*:\s*(?P<memo>.+)$", rest, flags=re.IGNORECASE)
    if memo_match is not None:
        memo = memo_match.group("memo").strip(" .,")
        rest = rest[: memo_match.start()].strip(" .,")
    all_day = relative_default_all_day or "종일" in rest
    profile = "family" if "가족" in rest else "main"
    title = rest
    title = re.sub(r"(?:을|를)?\s*종일\s*일정으로", " ", title)
    title = re.sub(r"(?:을|를)?\s*일정으로", " ", title)
    title = re.sub(r"\b종일\b", " ", title)
    title = re.sub(r"가족(?:에|으로)?", " ", title)
    title = re.sub(r"추가(?:해줘|해|해라|좀)?", " ", title)
    title = " ".join(title.split()).strip(" .,")
    if not title or _is_view_only_title(title):
        return None
    return EventCreateRequest(
        title=title,
        start_date=start.isoformat(),
        end_date=start.isoformat(),
        all_day=all_day,
        memo=memo,
        profile=profile,
    )


def _prefixed_event_body(text: str) -> str:
    match = re.match(r"^(?:일정|event)\s*[,，;；:：]\s*(?P<body>.+)$", text, flags=re.IGNORECASE)
    if match is None:
        return ""
    return match.group("body").strip()


def _split_inline_memo(text: str) -> tuple[str, str]:
    if "::" not in text:
        return text, ""
    body, memo = text.split("::", 1)
    return body.strip(" .,"), memo.strip(" .,")


def _relative_event_date(text: str, *, today: date) -> tuple[date, str, str] | None:
    match = re.match(
        r"^(?P<scope>가족|family)?\s*(?P<label>오늘|내일|모레|today|tomorrow)\s+(?P<body>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None

    label = match.group("label").lower()
    if label in {"내일", "tomorrow"}:
        start = today + timedelta(days=1)
    elif label == "모레":
        start = today + timedelta(days=2)
    else:
        start = today
    rest, memo = _split_inline_memo(match.group("body").strip(" .,"))
    if match.group("scope"):
        rest = f"{match.group('scope')} {rest}".strip()
    return start, rest, memo


def _is_view_only_title(title: str) -> bool:
    lowered = title.lower()
    cleaned = lowered
    for marker in ("보여줘", "보여", "알려줘", "알려", "일정", "스케줄", "캘린더", "calendar", "show", "?"):
        cleaned = cleaned.replace(marker, " ")
    return not " ".join(cleaned.split())
