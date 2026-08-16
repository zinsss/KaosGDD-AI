from __future__ import annotations

from dataclasses import dataclass
import re


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


@dataclass(frozen=True)
class MemoEditRequest:
    query: str
    content: str


def parse_memo_create(content: str) -> MemoCreateRequest | None:
    text = content.strip()
    if _is_status_announcement(text):
        return None
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
    if _is_status_announcement(text):
        return None
    if "메모" not in text:
        return None
    for marker in ("삭제했어요", "삭제했어", "삭제해줘", "삭제", "지워줘", "지워", "없애줘", "없애"):
        if marker not in text:
            continue
        query = text.replace(marker, " ", 1).replace("메모", " ")
        query = " ".join(query.split()).strip(" :")
        if query:
            return MemoDeleteRequest(query)
    return None


def parse_memo_edit(content: str) -> MemoEditRequest | None:
    text = content.strip()
    if _is_status_announcement(text):
        return None
    if "메모" not in text:
        return None
    for pattern in (
        r"^메모\s+(?P<query>.+?)\s+(?:수정|편집|변경|바꿔줘)\s*:\s*(?P<content>.+)$",
        r"^(?P<query>.+?)\s*메모(?:를|을)?\s+(?P<content>.+?)\s*(?:수정해줘|수정|편집해줘|편집|변경해줘|변경|바꿔줘)$",
    ):
        match = re.match(pattern, text, flags=re.DOTALL)
        if not match:
            continue
        query = " ".join(match.group("query").split()).strip(" :")
        new_content = _strip_replacement_suffix(match.group("content").strip())
        if query and new_content:
            return MemoEditRequest(query=query, content=new_content)
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


def _strip_replacement_suffix(value: str) -> str:
    compact = value.strip()
    if compact.endswith("으로"):
        return compact[:-2].strip()
    if compact.endswith("로"):
        return compact[:-1].strip()
    return compact


def _is_status_announcement(text: str) -> bool:
    compact = " ".join(text.strip().split())
    if not compact or "메모" not in compact:
        return False
    actions = ("저장", "삭제", "수정", "변경", "편집", "복구")
    endings = ("했어요", "했어", "됐어요", "됐어", "되었습니다", "됨")
    if not any(action in compact for action in actions):
        return False
    remainder = compact.replace("메모", " ")
    for action in actions:
        remainder = remainder.replace(action, " ")
    for ending in endings:
        remainder = remainder.replace(ending, " ")
    remainder = remainder.replace("새로", " ").replace("를", " ").replace("을", " ").replace("가", " ")
    return not " ".join(remainder.split())
