from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .task_update_intent import TaskDueUpdateRequest
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
            return await self._get("/tools/memos/search", {"query": request.query, "limit": "5"})
        if request.kind is ToolKind.DOCUMENT_SEARCH:
            return await self._get("/tools/documents/search", {"query": request.query, "limit": "5"})
        raise GovernorToolError("unsupported Governor tool")

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
    task = payload.get("task")
    if not isinstance(task, dict):
        return "Task updated."
    title = str(task.get("title") or "Untitled task")
    new_due = _due_text(str(task.get("newDue") or ""), str(task.get("newDueTime") or ""))
    return f"Task updated: {title} -> {new_due}"


def _due_text(due_date: str, due_time: str) -> str:
    return " ".join(part for part in (due_date, due_time) if part).strip()


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
    heading = f"Memos search: {query} ({payload.get('count', len(results))} results)"
    if not results:
        return f"{heading}\n- none"
    return "\n".join([heading, *(_memo_line(item) for item in results[:5])])


def _render_documents(query: str, payload: dict[str, Any]) -> str:
    results = _items(payload.get("results"))
    total = payload.get("total") or payload.get("count") or len(results)
    heading = f"Document search: {query} ({total} results)"
    if not results:
        return f"{heading}\n- none"
    return "\n".join([heading, *(_document_line(item) for item in results[:5])])


def _items(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


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
    title = str(item.get("title") or item.get("name") or "Untitled memo").strip()
    snippet = str(item.get("snippet") or "").strip()
    return f"- {title}: {snippet}" if snippet else f"- {title}"


def _document_line(item: dict[str, Any]) -> str:
    title = str(item.get("title") or item.get("originalFileName") or item.get("filename") or "Untitled document").strip()
    created = str(item.get("created") or item.get("createdDate") or "").strip()
    return f"- {title} - {created}" if created else f"- {title}"
