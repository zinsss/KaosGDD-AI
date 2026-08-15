from __future__ import annotations

from dataclasses import dataclass


CREATE_MARKERS = (
    "메모해줘",
    "메모에 저장해줘",
    "메모로 저장해줘",
    "기록해줘",
)


@dataclass(frozen=True)
class MemoCreateRequest:
    content: str


@dataclass(frozen=True)
class MemoDeleteRequest:
    query: str


def parse_memo_create(content: str) -> MemoCreateRequest | None:
    text = content.strip()
    if not text:
        return None
    for marker in CREATE_MARKERS:
        parsed = _content_after_prefix(text, marker)
        if parsed:
            return MemoCreateRequest(parsed)
        parsed = _content_before_suffix(text, marker)
        if parsed:
            return MemoCreateRequest(parsed)
    return None


def parse_memo_delete(content: str) -> MemoDeleteRequest | None:
    text = " ".join(content.strip().split())
    if "메모" not in text:
        return None
    for marker in ("삭제해줘", "삭제", "지워줘", "지워", "없애줘", "없애"):
        if marker not in text:
            continue
        query = text.replace(marker, " ", 1).replace("메모", " ")
        query = " ".join(query.split()).strip(" :")
        if query:
            return MemoDeleteRequest(query)
    return None


def _content_after_prefix(text: str, marker: str) -> str:
    if not text.startswith(marker):
        return ""
    value = text[len(marker) :].strip()
    return value.removeprefix(":").strip()


def _content_before_suffix(text: str, marker: str) -> str:
    if not text.endswith(marker):
        return ""
    return text[: -len(marker)].strip(" :")
