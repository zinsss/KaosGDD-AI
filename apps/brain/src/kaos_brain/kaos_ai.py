from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import re
from uuid import uuid4
from typing import Any, Mapping, Protocol

from .brain_guard import INTENT_PARAMETER_KEYS, MUTATION_INTENTS, READONLY_INTENTS


class KaosAIError(RuntimeError):
    """Raised when the legacy KaosAI/KaosBrain-OpenAI provider cannot return a usable plan."""


class KaosAIPlanner(Protocol):
    async def plan(self, user_text: str, *, context: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return a KaosBrain-OpenAI plan or None when planning is unavailable."""

    async def preview_calendar_events(self, request: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Return preview-only calendar event proposals."""

    async def suggest_document_tags(self, context: Mapping[str, Any]) -> tuple[str, ...]:
        """Return existing Paperless tag names suggested for a document."""

    async def preview_official_memo(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Return a preview-only Memos draft for an official document/source."""

    async def second_look(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Return a temporary medical image second-look result."""


@dataclass(frozen=True)
class KaosAIConfig:
    enabled: bool = False
    provider: str = "disabled"
    base_url: str = ""
    model: str = "default"
    api_token: str = ""
    timeout_seconds: int = 30


class DisabledKaosAIPlanner:
    async def plan(self, user_text: str, *, context: Mapping[str, Any]) -> dict[str, Any] | None:
        return None

    async def preview_calendar_events(self, request: Mapping[str, Any]) -> list[dict[str, Any]]:
        raise KaosAIError("kaosai_disabled")

    async def suggest_document_tags(self, context: Mapping[str, Any]) -> tuple[str, ...]:
        return ()

    async def preview_official_memo(self, request: Mapping[str, Any]) -> dict[str, Any]:
        raise KaosAIError("kaosai_disabled")

    async def second_look(self, request: Mapping[str, Any]) -> dict[str, Any]:
        raise KaosAIError("kaosai_disabled")


class OpenClawKaosAIPlanner:
    def __init__(self, config: KaosAIConfig) -> None:
        self.config = config

    async def plan(self, user_text: str, *, context: Mapping[str, Any]) -> dict[str, Any] | None:
        if not self.config.enabled:
            return None
        raw = await self._complete(user_text, context=context)
        return normalize_kaosai_plan_scope(user_text, parse_kaosai_plan_response(raw))

    async def preview_calendar_events(self, request: Mapping[str, Any]) -> list[dict[str, Any]]:
        if not self.config.enabled:
            raise KaosAIError("kaosai_disabled")
        raw = await self._complete_message(f"{KAOSAI_CALENDAR_PREVIEW_SYSTEM_PROMPT}\n\n{_render_calendar_preview_request(request)}")
        return parse_calendar_preview_response(raw, request)

    async def suggest_document_tags(self, context: Mapping[str, Any]) -> tuple[str, ...]:
        if not self.config.enabled:
            return ()
        raw = await self._complete_message(f"{KAOSAI_DOCUMENT_TAG_SYSTEM_PROMPT}\n\n{_render_document_tag_request(context)}")
        return merge_document_tag_suggestions(document_tag_rule_suggestions(context), parse_document_tag_response(raw, context))

    async def preview_official_memo(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise KaosAIError("kaosai_disabled")
        raw = await self._complete_message(f"{KAOSAI_OFFICIAL_MEMO_SYSTEM_PROMPT}\n\n{_render_official_memo_request(request)}")
        return parse_official_memo_response(raw, request)

    async def second_look(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise KaosAIError("kaosai_disabled")
        attachments = _render_second_look_attachments(request)
        if not attachments:
            raise KaosAIError("kaosai_second_look_missing_image")
        raw = await self._complete_message(
            f"{KAOSAI_SECOND_LOOK_SYSTEM_PROMPT}\n\n{_render_second_look_request(request)}",
            attachments=attachments,
        )
        return parse_second_look_response(raw, model=self.config.model or "default")

    async def _complete(self, user_text: str, *, context: Mapping[str, Any]) -> str:
        return await self._complete_message(f"{KAOSAI_PLAN_SYSTEM_PROMPT}\n\n{_render_plan_request(user_text, context)}")

    async def _complete_message(self, message: str, *, attachments: list[Mapping[str, str]] | None = None) -> str:
        import aiohttp

        if not self.config.api_token:
            raise KaosAIError("kaosai_gateway_token_required")
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.ws_connect(_openclaw_gateway_url(self.config.base_url)) as websocket:
                    await _openclaw_connect(websocket, token=self.config.api_token)
                    data = await _openclaw_agent_request(
                        websocket,
                        model=self.config.model,
                        message=message,
                        attachments=attachments,
                    )
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise KaosAIError("kaosai_request_timed_out") from exc
            except aiohttp.ClientError as exc:
                raise KaosAIError("kaosai_gateway_request_failed") from exc
            except ValueError as exc:
                raise KaosAIError("kaosai_gateway_response_not_json") from exc
        content = _extract_openclaw_text(data)
        if not content:
            raise KaosAIError("kaosai_response_empty")
        return content


def _format_intent_lines(intents: set[str]) -> str:
    return "\n".join(f"- {intent}" for intent in sorted(intents))


def _format_parameter_lines() -> str:
    lines = []
    for intent in sorted(INTENT_PARAMETER_KEYS):
        keys = ", ".join(sorted(INTENT_PARAMETER_KEYS[intent])) or "none"
        lines.append(f"- {intent}: {keys}")
    return "\n".join(lines)


KAOSAI_PLAN_SYSTEM_PROMPT = f"""You are KaosBrain-OpenAI, the OpenAI-backed planner for KaosGDD.
Return exactly one JSON object and no markdown.
You may understand language and draft plans, but you cannot call tools.
KaosBrain will validate your plan before KaosGovernor can write anything.

Allowed schema:
{{
  "intent": "<allowed intent>",
  "scope": "personal|family|supplies",
  "parameters": {{}}
}}

Allowed read-only intents:
{_format_intent_lines(READONLY_INTENTS)}

Allowed mutation intents:
{_format_intent_lines(MUTATION_INTENTS)}

Allowed parameters by intent:
{_format_parameter_lines()}

Rules:
- Use YYYY-MM-DD dates.
- Use HH:MM 24-hour times.
- Default scope to "personal" unless the user explicitly says family, wife, spouse, child, Rouny, shared, supplies, or household context.
- Use "family" only for explicitly shared family calendar/task requests.
- Use "supplies" only for supplies, shopping, inventory, or household stock items.
- Default task due time to 10:00 when a due date has no time.
- Do not produce shell, Docker, database, restart, filesystem, SSH, or admin intents.
- Use system.status only for read-only health, status, and service-check requests.
- For supplies, do not include dueDate or dueTime.
- If the user asks for a state change, set the matching mutation intent. KaosGovernor will ask for confirmation.
- If the request is ambiguous, return {{"intent":"clarify","scope":"personal","parameters":{{"question":"..."}}}}."""


KAOSAI_DOCUMENT_TAG_SYSTEM_PROMPT = """You are KaosBrain-OpenAI helping KaosBrain choose Paperless tags.
Return exactly one JSON object and no markdown.
Allowed schema:
{"tags":["tag name"]}

Rules:
- Prefer tag names from availableTags when they fit.
- For the KaosGDD PWA flow, suggest only tags present in availableTags.
- Use at most 5 tags.
- Prefer tags supported by the document title, filename, correspondent, and contentExcerpt.
- Return {"tags":[]} when no tag clearly fits."""


KAOSAI_CALENDAR_PREVIEW_SYSTEM_PROMPT = """You are KaosBrain-OpenAI helping KaosGDD turn short Family calendar notes into preview-only event proposals.
Return exactly one JSON object and no markdown.
Allowed schema:
{"events":[{"title":"...","allDay":true,"startDate":"YYYY-MM-DD","startTime":"","endDate":"YYYY-MM-DD","endTime":""},{"title":"...","allDay":false,"startDate":"YYYY-MM-DD","startTime":"HH:MM","endDate":"YYYY-MM-DD","endTime":"HH:MM"}]}

Rules:
- This is preview only. Do not write, save, call tools, or claim anything was created.
- Use the request date as the default date.
- Split bundled day notes into separate events when they are separated by slash, newline, comma, +, &, or Korean connectors such as "그리고", "그 다음", "다음", "또", and "및".
- Keep Korean titles natural and concise.
- Preserve explicitly provided start times.
- Use HH:MM 24-hour times.
- If a timed event has a start but no end, make it 1 hour long.
- If a timed event has an end earlier than or equal to the start, treat it as overnight on the next date.
- Make items without a time all-day events.
- Return at most 12 events.
- If the text is unclear, still return the safest preview; KaosGDD will show it for confirmation before any save."""


KAOSAI_OFFICIAL_MEMO_SYSTEM_PROMPT = """You are KaosBrain-OpenAI helping KaosGDD turn an official source into a Memos-ready summary.
Return exactly one JSON object and no markdown wrapper.
Allowed schema:
{"title":"...","content":"...","sourceTitle":"...","sourceUrl":"...","checkedAt":"YYYY-MM-DD"}

Rules:
- This is preview only. Do not write, save, call tools, or claim anything was created.
- Use Korean unless the source/request is clearly English.
- Summarize only facts supported by sourceText. If the source does not state something, say so plainly.
- Prefer a practical memo format: short overview, key points, dates/eligibility/actions, and source/check date.
- Keep the title natural and concise.
- Put the source URL and checked date in the memo content when available.
- Do not invent official policies, prices, dates, contacts, or links."""


KAOSAI_SECOND_LOOK_SYSTEM_PROMPT = """You are KaosBrain-OpenAI providing a temporary medical image second-look checklist.
Return exactly one JSON object and no markdown.
Do not diagnose, do not claim certainty, and do not provide a final report.
Use Korean unless the user question is clearly in another language.

Allowed schema:
{
  "summary": "...",
  "checklist": ["..."],
  "cautions": ["..."],
  "recommendation": "..."
}

Rules:
- Review only the attached rendered preview image.
- Focus on visible image-quality issues and easy-to-miss review checklist points.
- Use second-look wording such as possible, consider, visible concern, and needs physician review.
- Avoid final diagnosis language and never phrase the output as a clinical report.
- Mention that final judgment belongs to the clinician.
- Do not infer hidden DICOM metadata.
- Do not suggest that PACS, Orthanc, or medical records were modified."""


def parse_kaosai_plan_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise KaosAIError("empty_kaosai_response")
    if text.startswith("```"):
        text = _strip_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KaosAIError("invalid_kaosai_json") from exc
    if not isinstance(payload, dict):
        raise KaosAIError("kaosai_plan_must_be_object")
    intent = str(payload.get("intent") or "").strip()
    parameters = payload.get("parameters")
    if not intent:
        raise KaosAIError("kaosai_intent_required")
    if intent == "clarify":
        question = ""
        if isinstance(parameters, Mapping):
            question = str(parameters.get("question") or "").strip()
        if not question:
            raise KaosAIError("kaosai_clarify_question_required")
        return dict(payload)
    if not isinstance(parameters, Mapping):
        raise KaosAIError("kaosai_parameters_required")
    return dict(payload)


def parse_document_tag_response(raw: str, context: Mapping[str, Any]) -> tuple[str, ...]:
    text = raw.strip()
    if text.startswith("```"):
        text = _strip_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KaosAIError("invalid_document_tag_json") from exc
    if not isinstance(payload, Mapping):
        raise KaosAIError("document_tag_response_must_be_object")
    available = _available_tags_by_normalized_name(context)
    selected: list[str] = []
    raw_tags = payload.get("tags")
    if not isinstance(raw_tags, list):
        raise KaosAIError("document_tag_tags_required")
    for raw_tag in raw_tags:
        candidate = _clean_document_tag(raw_tag)
        tag = available.get(_normalize_tag_name(candidate), candidate)
        if tag and tag not in selected:
            selected.append(tag)
        if len(selected) >= 5:
            break
    return tuple(selected)


def parse_calendar_preview_response(raw: str, request: Mapping[str, Any]) -> list[dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        text = _strip_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KaosAIError("invalid_calendar_preview_json") from exc
    if not isinstance(payload, Mapping):
        raise KaosAIError("calendar_preview_response_must_be_object")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise KaosAIError("calendar_preview_events_required")
    date_value = _calendar_preview_date(request)
    events: list[dict[str, Any]] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, Mapping):
            raise KaosAIError("calendar_preview_event_must_be_object")
        events.append(_normalize_calendar_preview_event(raw_event, default_date=date_value))
        if len(events) >= 12:
            break
    return events


def parse_official_memo_response(raw: str, request: Mapping[str, Any]) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = _strip_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KaosAIError("invalid_official_memo_json") from exc
    if not isinstance(payload, Mapping):
        raise KaosAIError("official_memo_response_must_be_object")
    title = " ".join(str(payload.get("title") or "").split())
    content = str(payload.get("content") or "").strip()
    if not title:
        raise KaosAIError("official_memo_title_required")
    if not content:
        raise KaosAIError("official_memo_content_required")
    source = request.get("source") if isinstance(request.get("source"), Mapping) else {}
    source_title = " ".join(str(payload.get("sourceTitle") or source.get("title") or "").split())[:200]
    source_url = str(payload.get("sourceUrl") or source.get("url") or "").strip()[:500]
    checked_at = str(payload.get("checkedAt") or request.get("checkedAt") or "").strip()[:40]
    if not content.lstrip().startswith("#"):
        content = f"# {title}\n\n{content}"
    return {
        "title": title[:160],
        "content": content[:7900],
        "sourceTitle": source_title,
        "sourceUrl": source_url,
        "checkedAt": checked_at,
    }


def document_tag_rule_suggestions(context: Mapping[str, Any]) -> tuple[str, ...]:
    available = _available_tags_by_normalized_name(context)
    selected: list[str] = []

    def add(candidate: str) -> None:
        tag = available.get(_normalize_tag_name(candidate), _clean_document_tag(candidate))
        if tag and tag not in selected and len(selected) < 5:
            selected.append(tag)

    text = _document_tag_text(context)
    if "이수" in text:
        add("이수증")
    if "수료" in text:
        add("수료증")
    for tag in _document_keyword_tags(text):
        add(tag)
    for name in _document_person_names(text):
        add(name)
    years = _document_years(context)
    for year in years:
        add(year)
    return tuple(selected)


def merge_document_tag_suggestions(*groups: tuple[str, ...]) -> tuple[str, ...]:
    selected: list[str] = []
    for group in groups:
        for tag in group:
            if tag and tag not in selected:
                selected.append(tag)
            if len(selected) >= 5:
                return tuple(selected)
    return tuple(selected)


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text[:500])
        if len(items) >= limit:
            break
    return items


def parse_second_look_response(raw: str, *, model: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = _strip_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"summary": raw, "checklist": [], "cautions": [], "recommendation": ""}
    if not isinstance(payload, Mapping):
        payload = {"summary": raw, "checklist": [], "cautions": [], "recommendation": ""}
    summary = str(payload.get("summary") or "").strip() or raw.strip()[:1000]
    checklist = _string_list(payload.get("checklist"), limit=8)
    cautions = _string_list(payload.get("cautions"), limit=5)
    recommendation = str(payload.get("recommendation") or "").strip()
    if not cautions:
        cautions = ["AI 보조 검토입니다. 최종 판단은 진료자가 합니다."]
    return {
        "summary": summary[:1400],
        "checklist": checklist,
        "cautions": cautions,
        "recommendation": recommendation[:800],
        "disclaimer": "AI 보조 검토입니다. 최종 판단은 진료자가 합니다.",
        "model": model,
    }


def _available_tags_by_normalized_name(context: Mapping[str, Any]) -> dict[str, str]:
    return {
        _normalize_tag_name(item.get("name")): str(item.get("name") or "").strip()
        for item in _available_tag_items(context)
        if str(item.get("name") or "").strip()
    }


def _normalize_tag_name(value: object) -> str:
    return _clean_document_tag(value).casefold()


def _clean_document_tag(value: object) -> str:
    return re.sub(r"[\x00-\x1f\x7f#]+", "", str(value or "")).strip()[:100]


def _calendar_preview_date(source: Mapping[str, Any]) -> str:
    raw = str(source.get("date") or source.get("startDate") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return ""
    try:
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    except ValueError:
        return ""


def _calendar_preview_time(value: object) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        return ""
    hour, minute = (int(part) for part in raw.split(":", 1))
    if hour > 23 or minute > 59:
        return ""
    return raw


def _calendar_preview_at(date_value: str, time_value: str) -> int:
    year, month, day = (int(part) for part in date_value.split("-", 2))
    hour, minute = (int(part) for part in time_value.split(":", 1))
    return (((year * 12 + month) * 31 + day) * 24 + hour) * 60 + minute


def _normalize_calendar_preview_event(event: Mapping[str, Any], *, default_date: str) -> dict[str, Any]:
    title = str(event.get("title") or event.get("summary") or "").strip()
    if not title:
        raise KaosAIError("calendar_preview_title_required")
    start_date = _calendar_preview_date(event) or default_date
    if not start_date:
        raise KaosAIError("calendar_preview_date_required")
    end_date = _calendar_preview_date({"date": event.get("endDate")}) or start_date
    if bool(event.get("allDay")):
        return {
            "title": title[:500],
            "allDay": True,
            "startDate": start_date,
            "startTime": "",
            "endDate": end_date,
            "endTime": "",
        }
    start_time = _calendar_preview_time(event.get("startTime"))
    end_time = _calendar_preview_time(event.get("endTime"))
    if not start_time or not end_time:
        raise KaosAIError("calendar_preview_time_required")
    if _calendar_preview_at(end_date, end_time) <= _calendar_preview_at(start_date, start_time):
        raise KaosAIError("calendar_preview_range_invalid")
    return {
        "title": title[:500],
        "allDay": False,
        "startDate": start_date,
        "startTime": start_time,
        "endDate": end_date,
        "endTime": end_time,
    }


def _document_tag_text(context: Mapping[str, Any]) -> str:
    document = context.get("document") if isinstance(context.get("document"), Mapping) else {}
    if not isinstance(document, Mapping):
        document = {}
    parts = [
        document.get("title"),
        document.get("filename"),
        document.get("correspondent"),
        document.get("contentExcerpt"),
    ]
    return "\n".join(str(part or "") for part in parts)


def _document_years(context: Mapping[str, Any]) -> tuple[str, ...]:
    document = context.get("document") if isinstance(context.get("document"), Mapping) else {}
    if not isinstance(document, Mapping):
        document = {}
    semantic_text = "\n".join(
        str(part or "")
        for part in (
            document.get("title"),
            document.get("filename"),
            document.get("correspondent"),
            document.get("contentExcerpt"),
        )
    )
    years = re.findall(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)", semantic_text)
    if not years:
        years = re.findall(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)", str(document.get("created") or ""))
    return tuple(dict.fromkeys(years))


def _document_person_names(text: str) -> tuple[str, ...]:
    names: list[str] = []
    for match in re.finditer(r"(?:성\s*명|이름)\s*[:：]?\s*([가-힣]{2,5})", text):
        name = match.group(1).strip()
        if name not in names:
            names.append(name)
    return tuple(names)


def _document_keyword_tags(text: str) -> tuple[str, ...]:
    rules = (
        ("의료폐기물", "의료폐기물"),
        ("진료기록", "진료기록"),
        ("처방전", "처방전"),
        ("프린트", "프린트"),
    )
    tags: list[str] = []
    for needle, tag in rules:
        if needle in text and tag not in tags:
            tags.append(tag)
    return tuple(tags)


FAMILY_SCOPE_MARKERS = frozenset(
    {
        "family",
        "shared",
        "household",
        "wife",
        "spouse",
        "child",
        "rouny",
        "가족",
        "패밀리",
        "공유",
        "집",
        "가정",
        "와이프",
        "아내",
        "부인",
        "로운",
        "로운이",
        "아이",
        "애기",
    }
)


def normalize_kaosai_plan_scope(user_text: str, plan: dict[str, Any]) -> dict[str, Any]:
    scope = str(plan.get("scope") or "").strip().lower()
    if scope != "family":
        return plan
    lowered = user_text.casefold()
    if any(marker in lowered for marker in FAMILY_SCOPE_MARKERS):
        return plan
    normalized = dict(plan)
    normalized["scope"] = "personal"
    return normalized


def _strip_fence(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    if not lines[0].startswith("```"):
        return text
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _render_plan_request(user_text: str, context: Mapping[str, Any]) -> str:
    safe_context = {str(key): value for key, value in context.items() if key in {"actorId", "channelId", "today"}}
    return json.dumps(
        {
            "userText": user_text,
            "context": safe_context,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _render_document_tag_request(context: Mapping[str, Any]) -> str:
    document = context.get("document") if isinstance(context.get("document"), Mapping) else {}
    return json.dumps(
        {
            "document": {
                "id": document.get("id") if isinstance(document, Mapping) else "",
                "title": str(document.get("title") or "") if isinstance(document, Mapping) else "",
                "created": str(document.get("created") or "") if isinstance(document, Mapping) else "",
                "filename": str(document.get("filename") or "") if isinstance(document, Mapping) else "",
                "correspondent": str(document.get("correspondent") or "") if isinstance(document, Mapping) else "",
                "contentExcerpt": str(document.get("contentExcerpt") or "")[:4000] if isinstance(document, Mapping) else "",
            },
            "availableTags": [dict(item) for item in _available_tag_items(context)],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _render_calendar_preview_request(request: Mapping[str, Any]) -> str:
    grammar_events = request.get("grammarEvents")
    return json.dumps(
        {
            "text": str(request.get("text") or "")[:4000],
            "date": str(request.get("date") or ""),
            "profile": str(request.get("profile") or "family"),
            "grammarEvents": grammar_events if isinstance(grammar_events, list) else [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _render_official_memo_request(request: Mapping[str, Any]) -> str:
    source = request.get("source") if isinstance(request.get("source"), Mapping) else {}
    return json.dumps(
        {
            "prompt": str(request.get("prompt") or "")[:1200],
            "checkedAt": str(request.get("checkedAt") or ""),
            "source": {
                "type": str(source.get("type") or ""),
                "title": str(source.get("title") or "")[:200],
                "url": str(source.get("url") or "")[:500],
                "text": str(source.get("text") or "")[:20000],
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _render_second_look_request(request: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "source": request.get("source"),
            "requestId": request.get("requestId"),
            "modality": request.get("modality"),
            "bodyPart": request.get("bodyPart"),
            "viewPosition": request.get("viewPosition"),
            "aiDomain": request.get("aiDomain"),
            "question": request.get("question"),
            "safety": request.get("safety"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _render_second_look_attachments(request: Mapping[str, Any]) -> list[Mapping[str, str]]:
    attachments: list[Mapping[str, str]] = []
    images = request.get("images")
    if not isinstance(images, list):
        return attachments
    for index, image in enumerate(images[:4], start=1):
        if not isinstance(image, Mapping):
            continue
        image_format = str(image.get("format") or "").strip().lower()
        content = str(image.get("contentBase64") or "").strip()
        if image_format == "jpg":
            image_format = "jpeg"
        if image_format not in {"png", "jpeg"} or not content:
            continue
        attachments.append(
            {
                "mimeType": f"image/{image_format}",
                "content": content,
                "name": f"kaospacs-aio-second-look-{index}.{image_format}",
            }
        )
    return attachments


def _available_tag_items(context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = context.get("availableTags")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, Mapping)]


async def _openclaw_connect(websocket: Any, *, token: str) -> None:
    while True:
        frame = await _receive_openclaw_json(websocket)
        if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
            break
    request_id = str(uuid4())
    await websocket.send_json(
        {
            "type": "req",
            "id": request_id,
            "method": "connect",
            "params": {
                "minProtocol": 4,
                "maxProtocol": 4,
                "client": {
                    "id": "gateway-client",
                    "displayName": "KaosBrain",
                    "version": "0.0.0",
                    "platform": "linux",
                    "deviceFamily": "server",
                    "mode": "backend",
                    "instanceId": str(uuid4()),
                },
                "caps": [],
                "auth": {"token": token},
                "role": "operator",
                "scopes": ["operator.admin"],
            },
        }
    )
    frame = await _receive_openclaw_response(websocket, request_id, expect_final=False)
    if not frame.get("ok"):
        raise KaosAIError(_openclaw_error_code(frame, "kaosai_gateway_connect_failed"))


async def _openclaw_agent_request(
    websocket: Any,
    *,
    model: str,
    message: str,
    attachments: list[Mapping[str, str]] | None = None,
) -> Mapping[str, Any]:
    request_id = str(uuid4())
    session_id = f"kaosbrain-plan-{uuid4()}"
    model_name = model.strip()
    params: dict[str, Any] = {
        "message": message,
        "agentId": "main",
        "sessionId": session_id,
        "sessionKey": session_id,
        "modelRun": True,
        "promptMode": "none",
        "cleanupBundleMcpOnRunEnd": True,
        "idempotencyKey": str(uuid4()),
        "sessionEffects": "internal",
        "suppressPromptPersistence": True,
    }
    if model_name and model_name != "default":
        if "/" in model_name:
            provider, selected_model = model_name.split("/", 1)
            params["provider"] = provider
            params["model"] = selected_model
        else:
            params["model"] = model_name
    if attachments:
        params["attachments"] = [dict(item) for item in attachments]
    await websocket.send_json({"type": "req", "id": request_id, "method": "agent", "params": params})
    frame = await _receive_openclaw_response(websocket, request_id, expect_final=True)
    if not frame.get("ok"):
        raise KaosAIError(_openclaw_error_code(frame, "kaosai_gateway_agent_failed"))
    payload = frame.get("payload")
    if not isinstance(payload, Mapping):
        raise KaosAIError("kaosai_gateway_payload_invalid")
    return payload


async def _receive_openclaw_response(websocket: Any, request_id: str, *, expect_final: bool) -> Mapping[str, Any]:
    while True:
        frame = await _receive_openclaw_json(websocket)
        if frame.get("type") != "res" or frame.get("id") != request_id:
            continue
        if expect_final and isinstance(frame.get("payload"), Mapping) and frame["payload"].get("status") == "accepted":
            continue
        return frame


async def _receive_openclaw_json(websocket: Any) -> Mapping[str, Any]:
    import aiohttp

    message = await websocket.receive()
    if message.type == aiohttp.WSMsgType.TEXT:
        data = json.loads(message.data)
        if not isinstance(data, Mapping):
            raise KaosAIError("kaosai_gateway_frame_invalid")
        return data
    if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING}:
        raise KaosAIError("kaosai_gateway_closed")
    if message.type == aiohttp.WSMsgType.ERROR:
        raise KaosAIError("kaosai_gateway_error")
    raise KaosAIError("kaosai_gateway_frame_invalid")


def _extract_openclaw_text(data: Any) -> str:
    if not isinstance(data, Mapping):
        return ""
    result = data.get("result")
    if isinstance(result, Mapping):
        payloads = result.get("payloads")
        if isinstance(payloads, list):
            for payload in payloads:
                if isinstance(payload, Mapping) and isinstance(payload.get("text"), str):
                    return payload["text"].strip()
    for key in ("content", "response", "text", "summary"):
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _openclaw_gateway_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if value.startswith("ws://") or value.startswith("wss://"):
        return value
    if value.startswith("http://"):
        return f"ws://{value.removeprefix('http://')}"
    if value.startswith("https://"):
        return f"wss://{value.removeprefix('https://')}"
    return value


def _openclaw_error_code(frame: Mapping[str, Any], fallback: str) -> str:
    error = frame.get("error")
    if not isinstance(error, Mapping):
        return fallback
    code = str(error.get("code") or "").strip().lower()
    message = str(error.get("message") or "").strip()
    if code:
        return f"{fallback}:{code}"
    if message:
        return f"{fallback}:{message[:80]}"
    return fallback
