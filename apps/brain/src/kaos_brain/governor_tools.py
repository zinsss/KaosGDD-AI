from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .memo_intent import MemoCreateRequest, MemoDeleteRequest, MemoEditRequest
from .task_update_intent import TaskActionRequest, TaskCreateRequest, TaskDueUpdateRequest
from .tool_intent import ToolKind, ToolRequest


class GovernorToolError(RuntimeError):
    """Raised when KaosGovernor's Brain tool API cannot return a result."""


@dataclass(frozen=True)
class GovernorToolConfig:
    base_url: str
    api_token: str
    profile: str
    timeout_seconds: int


class GovernorToolClient:
    def __init__(self, config: GovernorToolConfig) -> None:
        self.config = config

    async def fetch(self, request: ToolRequest) -> dict[str, Any]:
        if request.kind is ToolKind.TODAY:
            return await self._get("/tools/today", {"profile": self.config.profile})
        if request.kind is ToolKind.ACTIVE_TASKS:
            return await self._get("/tools/tasks/active", {"profile": self.config.profile})
        if request.kind is ToolKind.MEMO_SEARCH:
            payload = await self._get("/tools/memos/search", {"query": request.query, "limit": "5"})
            return await self._with_single_memo_body(payload)
        if request.kind is ToolKind.DOCUMENT_SEARCH:
            payload = await self._get("/tools/documents/search", {"query": request.query, "limit": "5"})
            return await self._with_single_document_detail(payload)
        raise GovernorToolError("unsupported Governor tool")

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
                "profile": self.config.profile,
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
        return await self._post(
            "/tools/tasks/create/proposals",
            {
                "actorId": str(actor_id),
                "idempotencyKey": idempotency_key,
                "profile": self.config.profile,
                "title": request.title,
                "dueDate": request.due_date,
                "dueTime": request.due_time,
            },
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
                "profile": self.config.profile,
                "taskTitle": request.task_title,
                "action": request.action,
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

    async def approve_confirmation(self, confirmation_id: str, *, actor_id: int) -> dict[str, Any]:
        return await self._post(
            f"/tools/confirmations/{confirmation_id}/approve",
            {"actorId": str(actor_id)},
        )

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

    async def _post(self, path: str, payload: dict[str, str]) -> dict[str, Any]:
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
    return "할 일 수정했어요."


def render_task_create_proposal(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return "Task creation requires confirmation."
    title = str(task.get("title") or "Untitled task")
    due = _due_text(str(task.get("due") or ""), str(task.get("dueTime") or ""))
    return "\n".join(
        [
            "## Confirm new task",
            f"- task: {title}",
            f"- due: {due}",
        ]
    )


def render_task_create_completed(payload: dict[str, Any]) -> str:
    return "할 일 저장했어요."


def render_task_action_proposal(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return "Task action requires confirmation."
    title = str(task.get("title") or "Untitled task")
    action = str(task.get("action") or "update")
    label = "complete" if action == "complete" else "delete"
    due = _due_text(str(task.get("due") or ""), str(task.get("dueTime") or ""))
    lines = ["## Confirm task action", f"- action: {label}", f"- task: {title}"]
    if due:
        lines.append(f"- due: {due}")
    return "\n".join(lines)


def render_task_action_completed(payload: dict[str, Any]) -> str:
    task = payload.get("task")
    if not isinstance(task, dict):
        return "할 일 수정했어요."
    action = str(task.get("action") or "")
    if action == "delete":
        return "할 일 삭제했어요."
    if action == "complete":
        return "할 일 완료했어요."
    return "할 일 수정했어요."


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


def _due_text(due_date: str, due_time: str) -> str:
    return " ".join(part for part in (due_date, due_time) if part).strip()


def _memo_preview(content: str) -> str:
    preview = content.strip()
    if len(preview) > 1200:
        preview = f"{preview[:1200].rstrip()}..."
    return preview or "(empty)"


def render_tool_context(request: ToolRequest, payload: dict[str, Any]) -> str:
    if request.kind is ToolKind.TODAY:
        return _render_today(payload)
    if request.kind is ToolKind.ACTIVE_TASKS:
        return _render_tasks(payload)
    if request.kind is ToolKind.MEMO_SEARCH:
        return _render_memos(request.query, payload)
    if request.kind is ToolKind.DOCUMENT_SEARCH:
        return _render_documents(request.query, payload)
    return "No usable Governor data."


def _render_today(payload: dict[str, Any]) -> str:
    lines = [f"Today: {payload.get('date') or ''}".strip()]
    weather = payload.get("weather")
    if isinstance(weather, dict) and weather.get("summary"):
        lines.append(f"Weather: {weather['summary']}")
    events = _items(payload.get("events"))
    tasks = _items(payload.get("tasks"))
    lines.append("Events:")
    lines.extend(_event_line(item) for item in events) if events else lines.append("- none")
    lines.append("Due tasks:")
    lines.extend(_task_line(item) for item in tasks) if tasks else lines.append("- none")
    return "\n".join(lines)


def _render_tasks(payload: dict[str, Any]) -> str:
    tasks = _items(payload.get("tasks"))
    if not tasks:
        return "Active tasks: none"
    return "\n".join(["Active tasks:", *(_task_line(item) for item in tasks[:12])])


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
    lines.extend(_memo_line(item) for item in results[:5])
    return "\n".join(lines)


def _render_documents(query: str, payload: dict[str, Any]) -> str:
    results = _items(payload.get("results"))
    result_count = _count(payload, "resultCount", "count", fallback=len(results))
    total_count = _count(payload, "totalCount", "total", fallback=result_count)
    lines = [
        "Searched..",
        f"## {query or '..'}",
        f"{result_count} results in {total_count} documents",
    ]
    if not results:
        lines.append("- No matching documents.")
        return "\n".join(lines)
    if result_count > len(results):
        lines.append(f"- Showing first {len(results)} results.")
    lines.extend(_document_line(item) for item in results[:5])
    return "\n".join(lines)


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
    owner = str(item.get("ownerLabel") or item.get("owner") or "").strip()
    detail = " ".join(part for part in (time, title) if part)
    return f"- {detail} ({owner})" if owner else f"- {detail}"


def _task_line(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Untitled task").strip()
    due = str(item.get("due") or "").strip()
    due_time = str(item.get("dueTime") or "").strip()
    due_text = " ".join(part for part in (due, due_time) if part)
    return f"- {title} - {due_text}" if due_text else f"- {title}"


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


def _truncate(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit].rstrip()}..."


def _truncate_text(value: str, limit: int) -> str:
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit].rstrip()}..."


def _document_line(item: dict[str, Any]) -> str:
    title = _truncate(str(item.get("title") or item.get("originalFileName") or item.get("filename") or "Untitled document").strip(), 80)
    created = str(item.get("created") or item.get("createdDate") or "").strip()
    filename = str(item.get("filename") or item.get("originalFileName") or "").strip()
    correspondent = str(item.get("correspondent") or "").strip()
    details = [value for value in (created[:10], correspondent, filename) if value]
    if details:
        return f"### {title}\n- {_truncate(' · '.join(details), 180)}"
    return f"### {title}"


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
