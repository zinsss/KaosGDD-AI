from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .event_intent import EventCreateRequest
from .memo_intent import MemoCreateRequest, MemoDeleteRequest, MemoEditRequest
from .task_update_intent import TaskActionRequest, TaskCreateRequest, TaskDueUpdateRequest
from .tool_intent import ToolKind, ToolRequest


PERSONAL_EVENT_MARKER = "𝘎𝘋𝘋𝙕𝘪𝙉"
FAMILY_EVENT_MARKER = "𝘧𝘢𝘮𝘪𝘭𝘺"
FAMILY_EVENT_SUFFIX = f"  • {FAMILY_EVENT_MARKER}"


class GovernorToolError(RuntimeError):
    """Raised when KaosGovernor's Brain tool API cannot return a result."""


@dataclass(frozen=True)
class GovernorToolConfig:
    base_url: str
    api_token: str
    profile: str
    timeout_seconds: int
    supplies_collection_id: str = ""


@dataclass(frozen=True)
class TaskEditRequest:
    task_title: str
    title: str
    memo: str = ""
    due_date: str = ""
    due_time: str = ""
    priority: str = ""
    profile: str = ""
    collection_id: str = ""
    uid: str = ""


@dataclass(frozen=True)
class DocumentTagRequest:
    document_id: str
    tags: tuple[str, ...]


class GovernorToolClient:
    def __init__(self, config: GovernorToolConfig) -> None:
        self.config = config

    async def fetch(self, request: ToolRequest) -> dict[str, Any]:
        if request.kind is ToolKind.WEATHER:
            if request.collection_id.startswith("unsupported:"):
                return {
                    "weatherLocationUnsupported": request.query,
                    "supportedWeatherLocations": [
                        "포항",
                        "대구",
                        "서울",
                        "부산",
                        "울산",
                        "경주",
                        "영천",
                        "영해",
                        "영덕",
                        "제주",
                        "인천",
                        "대전",
                        "광주",
                    ],
                }
            return await self.today(profile=request.profile, city=request.collection_id)
        if request.kind is ToolKind.TODAY:
            return await self.today(profile=request.profile)
        if request.kind is ToolKind.UPCOMING_EVENTS:
            return await self._get("/tools/events/upcoming", {"profile": self._profile(request.profile), "days": "7"})
        if request.kind is ToolKind.CALENDAR_MONTH_IMAGE:
            return await self.calendar_month_image(profile=request.profile)
        if request.kind is ToolKind.RECENT_IMPORTS:
            return await self._get("/tools/imports/recent", {"profile": self._profile(request.profile)})
        if request.kind is ToolKind.ACTIVE_TASKS:
            return await self._get("/tools/tasks/active", self._task_params(request.profile, request.collection_id))
        if request.kind is ToolKind.COMPLETED_TASKS:
            return await self.completed_tasks(request, limit=25)
        if request.kind is ToolKind.MEMO_SEARCH:
            payload = await self._get("/tools/memos/search", {"query": request.query, "limit": "25"})
            return await self._with_single_memo_body(payload)
        if request.kind is ToolKind.DOCUMENT_SEARCH:
            return await self._get("/tools/documents/search", {"query": request.query, "limit": "25"})
        raise GovernorToolError("unsupported Governor tool")

    async def completed_tasks(self, request: ToolRequest, *, limit: int = 25) -> dict[str, Any]:
        params = {**self._task_params(request.profile, request.collection_id), "limit": str(limit)}
        if request.query:
            params["query"] = request.query
        if request.start:
            params["from"] = request.start
        if request.end:
            params["to"] = request.end
        return await self._get("/tools/tasks/completed", params)

    async def calendar_month_image(self, *, profile: str = "", year: int | None = None, month: int | None = None) -> dict[str, Any]:
        params = {"profile": self._profile(profile)}
        if year is not None:
            params["year"] = str(year)
        if month is not None:
            params["month"] = str(month)
        return await self._get("/tools/calendar/month-image", params)

    async def today(self, *, profile: str = "", day: object | None = None, city: str = "") -> dict[str, Any]:
        params = {"profile": self._profile(profile)}
        if day is not None:
            params["date"] = str(day)
        if city:
            params["city"] = city
        return await self._get("/tools/today", params)

    async def calendar_week(self, *, profile: str = "", start: object | None = None, days: int = 7) -> dict[str, Any]:
        params = {"profile": self._profile(profile), "days": str(days)}
        if start is not None:
            params["date"] = str(start)
        return await self._get("/tools/calendar/week", params)

    async def _with_single_memo_body(self, payload: dict[str, Any]) -> dict[str, Any]:
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != 1:
            return payload
        first = results[0]
        if not isinstance(first, dict):
            return payload
        name = str(first.get("name") or "").strip()
        memo_id = _memo_id(name)
        if not memo_id:
            return payload
        memo_payload = await self._get(f"/tools/memos/{quote(memo_id, safe='')}", {})
        memo = memo_payload.get("memo")
        if isinstance(memo, dict):
            payload = dict(payload)
            payload["results"] = [{**first, "content": str(memo.get("content") or ""), "full": True}]
        return payload

    async def get_memo(self, name: str) -> dict[str, Any]:
        memo_id = _memo_id(name)
        if not memo_id:
            raise GovernorToolError("invalid memo id")
        return await self._get(f"/tools/memos/{quote(memo_id, safe='')}", {})

    async def _with_single_document_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != 1:
            return payload
        first = results[0]
        if not isinstance(first, dict):
            return payload
        document_id = _document_id(first.get("id"))
        if not document_id:
            return payload
        document_payload = await self._get(f"/tools/documents/{document_id}", {})
        document = document_payload.get("document")
        if isinstance(document, dict):
            payload = dict(payload)
            payload["results"] = [{**first, **document, "full": True}]
        return payload

    async def get_document(self, document_id: object) -> dict[str, Any]:
        normalized = _document_id(document_id)
        if not normalized:
            raise GovernorToolError("invalid document id")
        return await self._get(f"/tools/documents/{normalized}", {})

    async def get_document_tag_context(self, document_id: object) -> dict[str, Any]:
        normalized = _document_id(document_id)
        if not normalized:
            raise GovernorToolError("invalid document id")
        return await self._get(f"/tools/documents/{normalized}/tag-context", {})

    async def propose_task_due_update(
        self,
        request: TaskDueUpdateRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/tasks/update-due/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "profile": self._profile(request.profile),
                **self._collection_payload(request.profile, request.collection_id),
                "taskTitle": request.task_title,
                "dueDate": request.due_date,
                "dueTime": request.due_time,
            },
        )

    async def propose_task_create(
        self,
        request: TaskCreateRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "actorId": str(actor_id),
            "idempotencyKey": idempotency_key,
            "profile": self._profile(request.profile),
            **self._collection_payload(request.profile, request.collection_id),
            "title": request.title,
        }
        if request.memo:
            payload["memo"] = request.memo
        if request.due_date:
            payload["dueDate"] = request.due_date
        if request.due_date and request.due_time:
            payload["dueTime"] = request.due_time
        return await self._post(
            "/tools/tasks/create/proposals",
            payload,
        )

    async def propose_task_action(
        self,
        request: TaskActionRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/tasks/action/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "profile": self._profile(request.profile),
                **self._collection_payload(request.profile, request.collection_id),
                "uid": request.uid,
                "taskTitle": request.task_title,
                "action": request.action,
            },
        )

    async def propose_task_edit(
        self,
        request: TaskEditRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/tasks/edit/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "profile": self._profile(request.profile),
                **self._collection_payload(request.profile, request.collection_id),
                "uid": request.uid,
                "taskTitle": request.task_title,
                "title": request.title,
                "memo": request.memo,
                "dueDate": request.due_date,
                "dueTime": request.due_time,
                "priority": request.priority,
            },
        )

    async def propose_event_create(
        self,
        request: EventCreateRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/events/create/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "profile": request.profile or self.config.profile,
                "title": request.title,
                "startDate": request.start_date,
                "endDate": request.end_date,
                "allDay": request.all_day,
                "memo": request.memo,
            },
        )

    async def propose_memo_create(
        self,
        request: MemoCreateRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/memos/create/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "content": request.content,
            },
        )

    async def propose_memo_delete(
        self,
        request: MemoDeleteRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/memos/delete/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "query": request.query,
            },
        )

    async def propose_memo_delete_by_name(
        self,
        name: str,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/memos/delete/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "name": name,
            },
        )

    async def propose_memo_edit(
        self,
        request: MemoEditRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/memos/edit/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "query": request.query,
                "content": request.content,
            },
        )

    async def propose_memo_edit_by_name(
        self,
        name: str,
        content: str,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            "/tools/memos/edit/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "name": name,
                "content": content,
            },
        )

    async def propose_document_tags(
        self,
        request: DocumentTagRequest,
        *,
        actor_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        document_id = _document_id(request.document_id)
        if not document_id:
            raise GovernorToolError("invalid document id")
        return await self._post(
            f"/tools/documents/{document_id}/tags/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "tags": list(request.tags),
            },
        )

    async def approve_confirmation(self, confirmation_id: str, *, actor_id: int) -> dict[str, Any]:
        return await self._post(
            f"/tools/confirmations/{confirmation_id}/approve",
            {"actorId": str(actor_id)},
        )

    def _profile(self, profile: str) -> str:
        return profile or self.config.profile

    def _collection_id(self, profile: str, collection_id: str) -> str:
        if collection_id:
            return collection_id
        if self._profile(profile) == "supplies":
            return self.config.supplies_collection_id
        return ""

    def _collection_payload(self, profile: str, collection_id: str) -> dict[str, str]:
        normalized = self._collection_id(profile, collection_id)
        return {"collectionId": normalized} if normalized else {}

    def _task_params(self, profile: str, collection_id: str) -> dict[str, str]:
        params = {"profile": self._profile(profile)}
        if resolved_collection_id := self._collection_id(profile, collection_id):
            params["collectionId"] = resolved_collection_id
        return params

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {"Authorization": f"Bearer {self.config.api_token}"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            try:
                async with session.get(f"{self.config.base_url.rstrip('/')}{path}", params=params) as response:
                    data = await response.json()
                    if response.status >= 400:
                        raise GovernorToolError(str(data.get("error") or f"http_{response.status}"))
                    if not isinstance(data, dict):
                        raise GovernorToolError("invalid Governor tool response")
                    return data
            except TimeoutError as exc:
                raise GovernorToolError("Governor tool request timed out") from exc
            except aiohttp.ClientError as exc:
                raise GovernorToolError("Governor tool request failed") from exc

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {"Authorization": f"Bearer {self.config.api_token}"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            try:
                async with session.post(f"{self.config.base_url.rstrip('/')}{path}", json=payload) as response:
                    data = await response.json()
                    if response.status >= 400:
                        raise GovernorToolError(str(data.get("error") or f"http_{response.status}"))
                    if not isinstance(data, dict):
                        raise GovernorToolError("invalid Governor tool response")
                    return data
            except TimeoutError as exc:
                raise GovernorToolError("Governor tool request timed out") from exc
            except aiohttp.ClientError as exc:
                raise GovernorToolError("Governor tool request failed") from exc


def render_task_due_update_proposal(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return "Task update requires confirmation."
    title = str(task.get("title") or "Untitled task")
    old_due = _due_text(str(task.get("oldDue") or ""), str(task.get("oldDueTime") or ""))
    new_due = _due_text(str(task.get("newDue") or ""), str(task.get("newDueTime") or ""))
    return "\n".join(
        [
            "## Confirm task edit",
            f"- task: {title}",
            f"- from: {old_due or 'none'}",
            f"- to: {new_due}",
        ]
    )


def render_task_due_update_completed(payload: dict[str, Any]) -> str:
    return f"{_task_noun(payload)} 수정했어요."


def render_task_edit_proposal(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return "Task edit requires confirmation."
    old_title = str(task.get("oldTitle") or "Untitled task")
    title = str(task.get("title") or old_title)
    old_due = _due_text(str(task.get("oldDue") or ""), str(task.get("oldDueTime") or ""))
    due = _due_text(str(task.get("due") or ""), str(task.get("dueTime") or ""))
    lines = ["## Confirm task edit", f"- from: {old_title}", f"- to: {title}"]
    if old_due or due:
        lines.append(f"- due: {old_due or 'none'} -> {due or 'none'}")
    return "\n".join(lines)


def render_task_edit_completed(payload: dict[str, Any]) -> str:
    return f"{_task_noun(payload)} 수정했어요."


def render_task_create_proposal(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return "Task creation requires confirmation."
    title = str(task.get("title") or "Untitled task")
    due = _due_text(str(task.get("due") or ""), str(task.get("dueTime") or ""))
    is_supplies = _task_noun(payload) == "비품"
    subject = "Supply" if is_supplies else "Task"
    lines = [
        f"Confirm New {subject}",
        f"## {title}",
    ]
    if due:
        lines.append(f"- due: {due}")
    memo = str(task.get("memo") or "").strip()
    if memo:
        lines.append(f"- memo: {memo}")
    return "\n".join(lines)


def render_task_create_completed(payload: dict[str, Any]) -> str:
    return "Supply added." if _task_noun(payload) == "비품" else "Task added."


def render_task_action_proposal(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return "Task action requires confirmation."
    title = str(task.get("title") or "Untitled task")
    action = str(task.get("action") or "update")
    label = {"complete": "complete", "delete": "delete", "reopen": "reopen"}.get(action, "update")
    due = _due_text(str(task.get("due") or ""), str(task.get("dueTime") or ""))
    lines = ["## Confirm task action", f"- action: {label}", f"- task: {title}"]
    if due:
        lines.append(f"- due: {due}")
    return "\n".join(lines)


def render_task_action_completed(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return f"{_task_noun(payload)} 수정했어요."
    action = str(task.get("action") or "")
    noun = _task_noun(payload)
    if action == "delete":
        return f"{noun} 삭제했어요."
    if action == "complete":
        return f"{noun} 완료했어요."
    if action == "reopen":
        return f"{noun} 다시 열었어요."
    return f"{noun} 수정했어요."


def render_event_create_proposal(payload: dict[str, Any]) -> str:
    event = payload.get("event")
    if not isinstance(event, dict):
        return "Event creation requires confirmation."
    lines = [
        "## Confirm new event",
        f"- event: {event.get('title') or 'Untitled event'}",
        f"- date: {event.get('startDate') or ''}",
    ]
    if event.get("allDay"):
        lines.append("- all day")
    memo = str(event.get("memo") or "").strip()
    if memo:
        lines.append(f"- memo: {memo}")
    return "\n".join(lines)


def render_event_create_completed(payload: dict[str, Any]) -> str:
    return "일정 저장했어요."


def render_memo_create_proposal(payload: dict[str, Any]) -> str:
    memo = payload.get("memo")
    if not isinstance(memo, dict):
        return "Memo creation requires confirmation."
    return "\n".join(
        [
            "## Confirm new memo",
            _memo_preview(str(memo.get("content") or "")),
        ]
    )


def render_memo_create_completed(payload: dict[str, Any]) -> str:
    return "메모 저장했어요."


def render_memo_delete_proposal(payload: dict[str, Any]) -> str:
    memo = payload.get("memo")
    if not isinstance(memo, dict):
        return "Memo delete requires confirmation."
    name = str(memo.get("name") or "").strip()
    content = str(memo.get("content") or memo.get("snippet") or "")
    lines = ["## Confirm memo delete"]
    if name:
        lines.append(f"- memo: {name}")
    lines.append(_memo_preview(content))
    return "\n".join(lines)


def render_memo_delete_completed(payload: dict[str, Any]) -> str:
    return "메모 삭제했어요."


def render_memo_edit_proposal(payload: dict[str, Any]) -> str:
    memo = payload.get("memo")
    if not isinstance(memo, dict):
        return "Memo edit requires confirmation."
    name = str(memo.get("name") or "").strip()
    old_content = str(memo.get("oldContent") or "")
    new_content = str(memo.get("newContent") or "")
    lines = ["## Confirm memo edit"]
    if name:
        lines.append(f"- memo: {name}")
    lines.extend(["### Current", _memo_preview(old_content), "### New", _memo_preview(new_content)])
    return "\n".join(lines)


def render_memo_edit_completed(payload: dict[str, Any]) -> str:
    return "메모 수정했어요."


def render_document_tags_proposal(payload: dict[str, Any]) -> str:
    document = payload.get("document")
    if not isinstance(document, dict):
        return "Document tag update requires confirmation."
    title = str(document.get("title") or "Untitled document")
    tags = _tag_text(document.get("tags"))
    ignored = _tag_text(payload.get("ignoredTags"))
    lines = ["## Confirm document tags", f"- document: {title}", f"- tags: {tags or 'none'}"]
    if ignored:
        lines.append(f"- ignored: {ignored}")
    return "\n".join(lines)


def render_document_tags_completed(payload: dict[str, Any]) -> str:
    return "문서 태그 수정했어요."


def _due_text(due_date: str, due_time: str) -> str:
    return " ".join(part for part in (due_date, due_time) if part).strip()


def _task_noun(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    task_payload = task if isinstance(task, dict) else payload
    profile = str(task_payload.get("profile") or payload.get("profile") or "").strip().lower()
    collection_id = str(task_payload.get("collectionId") or payload.get("collectionId") or "").strip().lower()
    return "비품" if profile == "supplies" or "supplies" in collection_id else "할 일"


def _memo_preview(content: str) -> str:
    preview = _escape_mentions(content).strip()
    if len(preview) > 1200:
        preview = f"{preview[:1200].rstrip()}..."
    return preview or "(empty)"


def _tag_text(values: object) -> str:
    if not isinstance(values, list | tuple):
        return ""
    tags = [str(value).strip().lstrip("#") for value in values if str(value).strip()]
    return ", ".join(f"#{tag}" for tag in tags)


def render_tool_context(request: ToolRequest, payload: dict[str, Any]) -> str:
    if request.kind is ToolKind.WEATHER:
        return _render_weather(request, payload)
    if request.kind is ToolKind.TODAY:
        return _render_today(payload)
    if request.kind is ToolKind.ACTIVE_TASKS:
        return _render_tasks(payload)
    if request.kind is ToolKind.COMPLETED_TASKS:
        return _render_completed_tasks(payload)
    if request.kind is ToolKind.MEMO_SEARCH:
        return _render_memos(request.query, payload)
    if request.kind is ToolKind.DOCUMENT_SEARCH:
        return _render_documents(request.query, payload)
    return "No usable Governor data."


def render_combined_search_context(
    query: str,
    memo_payload: dict[str, Any],
    document_payload: dict[str, Any],
) -> str:
    memo_results = _items(memo_payload.get("results"))
    document_results = _items(document_payload.get("results"))
    memo_count = _count(memo_payload, "resultCount", "count", fallback=len(memo_results))
    memo_total = _count(memo_payload, "totalCount", fallback=memo_count)
    document_count = _count(document_payload, "resultCount", "count", fallback=len(document_results))
    document_total = _count(document_payload, "totalCount", "total", fallback=document_count)
    lines = [
        "Searched..",
        f"## {query or '..'}",
        f"- Memos: {memo_count} results in {memo_total} memos",
        f"- Paperless: {document_count} results in {document_total} documents",
    ]
    if memo_count > 25:
        lines.append("- Memos: more than 25 found. First 25 shown.")
    if document_count > 25:
        lines.append("- Paperless: more than 25 found. First 25 shown.")
    if not memo_results:
        lines.append("- No matching memos.")
    if not document_results:
        lines.append("- No matching documents.")
    return "\n".join(lines)[:1900]


def render_memo_opened(query: str, item: dict[str, Any]) -> str:
    content = _escape_mentions(str(item.get("content") or item.get("snippet") or "")).strip()
    if content:
        return content[:1900]
    return f"## {memo_option_label(item)}"[:1900]


def render_memo_deleted(content: str, deleted_at: str) -> str:
    return f"{_escape_mentions(content).strip()}\n\nDeleted at {deleted_at}".strip()[:1900]


def render_document_opened(query: str, item: dict[str, Any]) -> str:
    title = document_display_title(item, 80)
    created = str(item.get("created") or item.get("createdDate") or "").strip()
    correspondent = str(item.get("correspondent") or "").strip()
    details = [value for value in (created[:10], correspondent) if value]
    lines = [f"## {title}"]
    if details:
        lines.append(f"- {_truncate(' · '.join(details), 180)}")
    url = str(item.get("url") or item.get("publicUrl") or "").strip()
    if url:
        lines.append(url)
    return "\n".join(lines)[:1900]


def search_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _items(payload.get("results"))


def memo_option_label(item: dict[str, Any]) -> str:
    return _truncate(_memo_title(item), 100)


def memo_option_description(item: dict[str, Any]) -> str:
    return _truncate(_memo_tags_text(item) or "No tags", 100)


def memo_public_url(base_url: str, name: str) -> str:
    memo_id = _memo_id(name)
    if not base_url or not memo_id:
        return ""
    return f"{base_url.rstrip('/')}/m/{memo_id}"


def document_option_label(item: dict[str, Any]) -> str:
    return document_display_title(item, 100)


def document_option_description(item: dict[str, Any]) -> str:
    details = [
        str(item.get("created") or item.get("createdDate") or "")[:10],
        str(item.get("correspondent") or ""),
    ]
    return _truncate(" · ".join(detail for detail in details if detail), 100)


def document_display_title(item: dict[str, Any], limit: int = 100) -> str:
    title = str(item.get("title") or "").strip()
    fallback = str(item.get("originalFileName") or item.get("filename") or "").strip()
    return _truncate(title or fallback or "Untitled document", limit)


def document_public_url(base_url: str, document_id: object) -> str:
    try:
        normalized = int(document_id)
    except (TypeError, ValueError):
        return ""
    if normalized <= 0 or not base_url:
        return ""
    return f"{base_url.rstrip('/')}/documents/{normalized}/details"


def _render_today(payload: dict[str, Any]) -> str:
    date_text = str(payload.get("date") or "").strip()
    lines = [f"## {date_text}" if date_text else "## 오늘"]
    weather = payload.get("weather")
    if isinstance(weather, dict) and weather.get("summary"):
        lines[0] = f"{lines[0]} · {weather['summary']}"
    events = _items(payload.get("events"))
    tasks = _items(payload.get("tasks"))
    if events:
        lines.append("### 일정")
        lines.extend(_event_line(item) for item in events)
    if tasks:
        lines.append("### 할 일")
        lines.extend(_task_line(item) for item in tasks)
    if not events and not tasks:
        lines.append("- 없음")
    return "\n".join(lines)


def _render_weather(request: ToolRequest, payload: dict[str, Any]) -> str:
    unsupported = str(payload.get("weatherLocationUnsupported") or "").strip()
    if unsupported:
        supported = payload.get("supportedWeatherLocations")
        supported_text = ", ".join(str(item) for item in supported) if isinstance(supported, list) else ""
        lines = [f"## {unsupported} 날씨", "- 지원하지 않는 위치예요."]
        if supported_text:
            lines.append(f"- 지원 위치: {supported_text}")
        return "\n".join(lines)
    date_text = str(payload.get("date") or "").strip()
    location = request.query.strip() or "날씨"
    title = f"## {location} 날씨" if location != "날씨" else "## 날씨"
    weather = payload.get("weather")
    if not isinstance(weather, dict) or not weather.get("summary"):
        return f"{title}\n- 조회 결과 없음"
    lines = [title, f"- {weather['summary']}"]
    detail = _weather_detail_line(weather)
    if detail:
        lines.append(f"- {detail}")
    dayparts = weather.get("dayparts")
    if isinstance(dayparts, list) and dayparts:
        lines.append("### 시간대")
        for part in dayparts:
            if isinstance(part, dict):
                part_line = _weather_daypart_line(part)
                if part_line:
                    lines.append(f"- {part_line}")
    if date_text:
        lines.append(f"- {date_text}")
    return "\n".join(lines)


def _weather_detail_line(weather: dict[str, Any]) -> str:
    parts = []
    precip_prob = _compact_weather_number(weather.get("precipitationProbability"))
    precip = _compact_weather_number(weather.get("precipitationMm"))
    humidity = _compact_weather_number(weather.get("humidityPercent"))
    wind = _compact_weather_number(weather.get("windSpeedKmh"))
    if precip_prob:
        parts.append(f"강수확률 {precip_prob}%")
    if precip:
        parts.append(f"강수량 {precip}mm")
    if humidity:
        parts.append(f"습도 {humidity}%")
    if wind:
        parts.append(f"바람 {wind}km/h")
    return " · ".join(parts)


def _weather_daypart_line(part: dict[str, Any]) -> str:
    label = _weather_daypart_label(str(part.get("label") or ""))
    glyph = str(part.get("glyph") or "").strip()
    temp = _weather_temp_range(part)
    details = _weather_detail_line(part)
    head = " ".join(value for value in (label, glyph, temp) if value)
    return f"{head} · {details}" if details else head


def _weather_daypart_label(label: str) -> str:
    return {
        "Morning": "오전",
        "Afternoon": "오후",
        "Evening": "저녁",
        "Night": "밤",
    }.get(label, label)


def _weather_temp_range(weather: dict[str, Any]) -> str:
    low = _compact_weather_number(weather.get("minTemp"))
    high = _compact_weather_number(weather.get("maxTemp"))
    return f"{low}-{high}℃" if low and high else ""


def _compact_weather_number(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(number)) if number.is_integer() else f"{number:.1f}".rstrip("0").rstrip(".")


def _render_tasks(payload: dict[str, Any]) -> str:
    tasks = _items(payload.get("tasks"))
    title = _task_list_title(payload, completed=False)
    if not tasks:
        return f"## {title}\n- 없음"
    return "\n".join([f"## {title}", *(_task_line(item) for item in tasks[:12])])


def _render_completed_tasks(payload: dict[str, Any]) -> str:
    tasks = _items(payload.get("tasks"))
    start = str(payload.get("from") or "").strip()
    end = str(payload.get("to") or "").strip()
    query = str(payload.get("query") or "").strip()
    title = _task_list_title(payload, completed=True)
    if query:
        title = f"{title} · {query}"
    if start or end:
        title = f"{title} · {start or '..'} ~ {end or '..'}"
    if not tasks:
        return f"## {title}\n- 없음"
    show_completed_date = not _task_list_is_supplies(payload)
    return "\n".join([f"## {title}", *(_completed_task_line(item, show_date=show_completed_date) for item in tasks[:25])])


def _task_list_title(payload: dict[str, Any], *, completed: bool) -> str:
    if _task_list_is_supplies(payload):
        return "완료한 비품" if completed else "비품"
    profile = str(payload.get("profile") or "").strip().lower()
    if profile == "family":
        return "완료한 가족 할 일" if completed else "가족 할 일"
    return "완료한 할 일" if completed else "할 일"


def _task_list_is_supplies(payload: dict[str, Any]) -> bool:
    profile = str(payload.get("profile") or "").strip().lower()
    collection_id = str(payload.get("collectionId") or "").strip().lower()
    return profile == "supplies" or "supplies" in collection_id


def _render_memos(query: str, payload: dict[str, Any]) -> str:
    results = _items(payload.get("results"))
    result_count = _count(payload, "resultCount", "count", fallback=len(results))
    total_count = _count(payload, "totalCount", fallback=result_count)
    lines = [
        "Searched..",
        f"## {query or '..'}",
        f"{result_count} results in {total_count} memos",
    ]
    if not results:
        lines.append("- No matching memos.")
        return "\n".join(lines)
    if result_count > len(results):
        lines.append(f"- Showing first {len(results)} results.")
    if len(results) > 1:
        return "\n".join(lines)
    lines.extend(_memo_line(item) for item in results[:5])
    return "\n".join(lines)


def _render_documents(query: str, payload: dict[str, Any]) -> str:
    results = _items(payload.get("results"))
    result_count = _count(payload, "resultCount", "count", fallback=len(results))
    total_count = _count(payload, "totalCount", "total", fallback=result_count)
    page = _count(payload, "page", fallback=1)
    page_size = _count(payload, "pageSize", "page_size", fallback=max(1, len(results) or 25))
    page_total = max(1, (result_count + page_size - 1) // page_size)
    lines = [
        "Searched..",
        f"## {query or '..'}",
        f"{result_count} results in {total_count} documents",
        f"Page {page} / {page_total}",
    ]
    if not results:
        lines.append("- No matching documents.")
        return "\n".join(lines)
    lines.extend(_document_link_line(item) for item in results[:25])
    return "\n".join(lines)[:1900]


def _items(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _count(payload: dict[str, Any], *keys: str, fallback: int) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return fallback


def _event_line(item: dict[str, Any]) -> str:
    time = str(item.get("time") or "").strip()
    title = str(item.get("title") or "Untitled event").strip()
    detail = " ".join(part for part in (time, title) if part)
    return f"- {detail}{_event_owner_suffix(item)}"


def _event_owner_suffix(item: dict[str, Any]) -> str:
    owner = str(item.get("owner") or item.get("ownerLabel") or "").strip().lower()
    return FAMILY_EVENT_SUFFIX if owner == "family" else ""


def _task_line(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Untitled task").strip()
    due = str(item.get("due") or "").strip()
    due_time = str(item.get("dueTime") or "").strip()
    due_text = " ".join(part for part in (due, due_time) if part)
    return f"- {title} - {due_text}" if due_text else f"- {title}"


def _completed_task_line(item: dict[str, Any], *, show_date: bool = True) -> str:
    title = str(item.get("title") or "Untitled task").strip()
    if not show_date:
        return f"- {title}"
    completed = str(item.get("completedDate") or item.get("due") or "").strip()
    return f"- {title} - {completed}" if completed else f"- {title}"


def _memo_line(item: dict[str, Any]) -> str:
    title = _memo_title(item)
    content = str(item.get("content") or "").strip()
    if content and item.get("full"):
        return f"### {title}\n{_truncate_text(content, 1400)}"
    snippet = str(item.get("snippet") or "").strip()
    if snippet:
        return f"### {title}\n- {_truncate(snippet, 180)}"
    return f"### {title}"


def _memo_title(item: dict[str, Any]) -> str:
    for source in (str(item.get("title") or ""), str(item.get("content") or ""), str(item.get("snippet") or "")):
        for raw in source.splitlines():
            title = raw.strip().lstrip("#").strip()
            if title:
                return _truncate(title, 80)
    return str(item.get("name") or "Untitled memo").strip()


def _memo_tags_text(item: dict[str, Any]) -> str:
    tags = item.get("tags")
    if not isinstance(tags, list):
        return ""
    cleaned = [str(tag).strip().lstrip("#") for tag in tags if str(tag).strip()]
    return ", ".join(f"#{tag}" for tag in cleaned)


def _strip_leading_title(content: str, title: str) -> str:
    normalized_title = title.strip()
    lines: list[str] = []
    skipped = False
    for raw in content.splitlines():
        if not skipped and not raw.strip():
            continue
        if not skipped and raw.strip().lstrip("#").strip() == normalized_title:
            skipped = True
            continue
        skipped = True
        lines.append(raw)
    return _truncate_text("\n".join(lines).strip() or content, 1500)


def _truncate(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: max(0, limit - 3)].rstrip()}..."


def _truncate_text(value: str, limit: int) -> str:
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit].rstrip()}..."


def _escape_mentions(value: str) -> str:
    return (
        value.replace("@everyone", "@\u200beveryone")
        .replace("@here", "@\u200bhere")
        .replace("<@&", "<@&\u200b")
        .replace("<@", "<@\u200b")
        .replace("<#", "<#\u200b")
    )


def _document_line(item: dict[str, Any]) -> str:
    title = document_display_title(item, 80)
    created = str(item.get("created") or item.get("createdDate") or "").strip()
    correspondent = str(item.get("correspondent") or "").strip()
    details = [value for value in (created[:10], correspondent) if value]
    if details:
        return f"### {title}\n- {_truncate(' · '.join(details), 180)}"
    return f"### {title}"


def _document_link_line(item: dict[str, Any]) -> str:
    title = document_display_title(item, 120)
    url = str(item.get("url") or item.get("publicUrl") or "").strip()
    suffix = f" · [open]({url})" if url else ""
    return f"- {title}{suffix}"


def _memo_id(name: str) -> str:
    if not name.startswith("memos/"):
        return ""
    memo_id = name.removeprefix("memos/").strip("/")
    return memo_id if memo_id and "/" not in memo_id else ""


def _document_id(value: object) -> str:
    if isinstance(value, bool):
        return ""
    try:
        document_id = int(value)
    except (TypeError, ValueError):
        return ""
    return str(document_id) if document_id > 0 else ""
