from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hmac
import logging
from typing import Any

from aiohttp import web
from kaos_governor import Actor, DurableGovernorError, MemoryDurableGovernorStore, OperationRequest
from kaos_governor.calendar import CalendarAdapterClient, CalendarAdapterError, profile_host
from kaos_governor.documents import DocumentIntakeError, PaperlessDocumentService
from kaos_governor.memos import MemosError, MemosService

from .calendar import weather_agenda_summary, weather_items_by_date


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingTaskDueUpdate:
    profile: str
    uid: str
    collection_id: str
    title: str
    old_due: str
    old_due_time: str
    new_due: str
    new_due_time: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PendingTaskCreate:
    profile: str
    collection_id: str
    title: str
    due: str
    due_time: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PendingTaskAction:
    profile: str
    action: str
    uid: str
    collection_id: str
    title: str
    due: str
    due_time: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PendingEventCreate:
    profile: str
    title: str
    start_date: str
    end_date: str
    all_day: bool
    memo: str
    collection_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PendingMemoCreate:
    content: str


@dataclass(frozen=True)
class PendingMemoDelete:
    name: str
    content: str


@dataclass(frozen=True)
class PendingMemoEdit:
    name: str
    old_content: str
    new_content: str


class BrainToolServer:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        governor_api_token: str,
        calendar_adapter: CalendarAdapterClient,
        memos: MemosService,
        paperless: PaperlessDocumentService,
        task_refresh_callback: Callable[[], Awaitable[None]] | None = None,
        today_provider: Callable[[], date] | None = None,
        durable_store: MemoryDurableGovernorStore | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._governor_api_token = governor_api_token
        self._calendar_adapter = calendar_adapter
        self._memos = memos
        self._paperless = paperless
        self._task_refresh_callback = task_refresh_callback
        self._today_provider = today_provider or date.today
        self._durable = durable_store or MemoryDurableGovernorStore()
        self._pending_task_due_updates: dict[str, PendingTaskDueUpdate] = {}
        self._pending_task_creates: dict[str, PendingTaskCreate] = {}
        self._pending_task_actions: dict[str, PendingTaskAction] = {}
        self._pending_event_creates: dict[str, PendingEventCreate] = {}
        self._pending_memo_creates: dict[str, PendingMemoCreate] = {}
        self._pending_memo_deletes: dict[str, PendingMemoDelete] = {}
        self._pending_memo_edits: dict[str, PendingMemoEdit] = {}
        self._runner: web.AppRunner | None = None

    def application(self) -> web.Application:
        app = web.Application(client_max_size=32 * 1024)
        app.middlewares.append(self._auth_middleware)
        app.router.add_get("/tools/today", self._today)
        app.router.add_get("/tools/tasks/active", self._active_tasks)
        app.router.add_get("/tools/tasks/completed", self._completed_tasks)
        app.router.add_get("/tools/memos/search", self._search_memos)
        app.router.add_get("/tools/memos/{memo_id}", self._get_memo)
        app.router.add_post("/tools/memos/create/proposals", self._propose_memo_create)
        app.router.add_post("/tools/memos/edit/proposals", self._propose_memo_edit)
        app.router.add_post("/tools/memos/delete/proposals", self._propose_memo_delete)
        app.router.add_get("/tools/documents/search", self._search_documents)
        app.router.add_get("/tools/documents/{document_id}", self._get_document)
        app.router.add_post("/tools/tasks/action/proposals", self._propose_task_action)
        app.router.add_post("/tools/tasks/create/proposals", self._propose_task_create)
        app.router.add_post("/tools/tasks/update-due/proposals", self._propose_task_due_update)
        app.router.add_post("/tools/events/create/proposals", self._propose_event_create)
        app.router.add_post("/tools/confirmations/{confirmation_id}/approve", self._approve_confirmation)
        return app

    async def start(self) -> None:
        self._runner = web.AppRunner(self.application(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self._host, self._port).start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        if not self._authorized(request):
            return web.json_response({"error": "governor_api_unauthorized"}, status=401)
        return await handler(request)

    def _authorized(self, request: web.Request) -> bool:
        if not self._governor_api_token:
            return False
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {self._governor_api_token}"
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    async def _today(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        current = _request_date(request, default=self._today_provider())
        days = [current]
        try:
            bootstrap = await asyncio.to_thread(self._calendar_adapter.bootstrap, profile)
            bootstrap = await asyncio.to_thread(self._with_weather, profile, bootstrap, days)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        return web.json_response(today_payload(bootstrap, profile=profile, current=current))

    async def _active_tasks(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        collection_id = request.query.get("collectionId", "").strip()
        try:
            tasks = await asyncio.to_thread(self._calendar_adapter.list_tasks, profile)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        active = active_task_payloads(tasks, collection_id=collection_id)
        return web.json_response(
            {
                "profile": profile,
                "collectionId": collection_id,
                "count": len(active),
                "tasks": active,
                "source": "calendar-adapter-live",
            }
        )

    async def _completed_tasks(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        collection_id = request.query.get("collectionId", "").strip()
        query = " ".join(request.query.get("query", "").split())
        start = _optional_request_date(request, "from")
        end = _optional_request_date(request, "to")
        limit = _limit(request, default=25)
        try:
            tasks = await asyncio.to_thread(self._calendar_adapter.list_tasks, profile)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        completed = completed_task_payloads(
            tasks,
            collection_id=collection_id,
            query=query,
            start=start,
            end=end,
            limit=limit,
        )
        return web.json_response(
            {
                "profile": profile,
                "collectionId": collection_id,
                "query": query,
                "from": start.isoformat() if start else "",
                "to": end.isoformat() if end else "",
                "count": len(completed),
                "tasks": completed,
                "source": "calendar-adapter-live",
            }
        )

    async def _search_memos(self, request: web.Request) -> web.Response:
        if not self._memos.config.enabled:
            return web.json_response({"error": "memos_search_disabled"}, status=503)
        query = " ".join(request.query.get("query", "").split())
        tags = request.query.getall("tag", [])
        limit = _limit(request, default=5)
        try:
            results = await asyncio.to_thread(self._memos.search, query, tags or None, limit)
        except (ValueError, MemosError) as exc:
            return _memos_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain Memos search failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response(
            {
                "query": query,
                "tags": tags,
                "count": len(results),
                "results": [result.as_dict() for result in results],
                "source": "memos-live",
            }
        )

    async def _get_memo(self, request: web.Request) -> web.Response:
        if not self._memos.config.enabled:
            return web.json_response({"error": "memos_search_disabled"}, status=503)
        try:
            memo = await asyncio.to_thread(self._memos.get, f"memos/{request.match_info['memo_id']}")
        except (ValueError, MemosError) as exc:
            return _memos_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain Memos fetch failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response({"memo": memo.as_dict(), "source": "memos-live"})

    async def _search_documents(self, request: web.Request) -> web.Response:
        query = " ".join(request.query.get("query", "").split())
        limit = _limit(request, default=5)
        try:
            page = await asyncio.to_thread(self._paperless.search_page, query, limit=limit)
        except DocumentIntakeError as exc:
            return _document_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain document search failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response({**page.as_dict(), "source": "paperless-live"})

    async def _get_document(self, request: web.Request) -> web.Response:
        try:
            document = await asyncio.to_thread(self._paperless.get, request.match_info["document_id"])
        except DocumentIntakeError as exc:
            return _document_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain document fetch failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response({"document": document.as_dict(), "source": "paperless-live"})

    async def _propose_memo_create(self, request: web.Request) -> web.Response:
        if not self._memos.config.enabled:
            return web.json_response({"error": "memos_create_disabled"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        content = str(body.get("content") or "").strip()
        if not actor_id or not idempotency_key or not content:
            return web.json_response({"error": "memo_create_missing_required_field"}, status=400)
        try:
            actor = Actor("user", actor_id, "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="memos",
                    operation_type="create",
                    parameters={"content": content},
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        pending = PendingMemoCreate(content=content)
        self._pending_memo_creates[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "memo": _pending_memo_create_payload(pending),
                "source": "memos-live",
            },
            status=201,
        )

    async def _propose_memo_delete(self, request: web.Request) -> web.Response:
        if not self._memos.config.enabled:
            return web.json_response({"error": "memos_delete_disabled"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        name = str(body.get("name") or "").strip()
        query = " ".join(str(body.get("query") or "").split())
        if not actor_id or not idempotency_key or not (name or query):
            return web.json_response({"error": "memo_delete_missing_required_field"}, status=400)
        try:
            match = await self._find_memo_for_write(name=name, query=query)
            if isinstance(match, web.Response):
                return match
            memo = match
            actor = Actor("user", actor_id, "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="memos",
                    operation_type="delete",
                    parameters={"name": memo.name, "query": query},
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (ValueError, MemosError) as exc:
            return _memos_error(exc)
        pending = PendingMemoDelete(name=memo.name, content=memo.content)
        self._pending_memo_deletes[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "memo": _pending_memo_delete_payload(pending),
                "source": "memos-live",
            },
            status=201,
        )

    async def _propose_memo_edit(self, request: web.Request) -> web.Response:
        if not self._memos.config.enabled:
            return web.json_response({"error": "memos_edit_disabled"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        name = str(body.get("name") or "").strip()
        query = " ".join(str(body.get("query") or "").split())
        content = str(body.get("content") or "").strip()
        if not actor_id or not idempotency_key or not (name or query) or not content:
            return web.json_response({"error": "memo_edit_missing_required_field"}, status=400)
        try:
            match = await self._find_memo_for_write(name=name, query=query)
            if isinstance(match, web.Response):
                return match
            memo = match
            actor = Actor("user", actor_id, "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="memos",
                    operation_type="edit",
                    parameters={"name": memo.name, "query": query, "content": content},
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (ValueError, MemosError) as exc:
            return _memos_error(exc)
        pending = PendingMemoEdit(name=memo.name, old_content=memo.content, new_content=content)
        self._pending_memo_edits[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "memo": _pending_memo_edit_payload(pending),
                "source": "memos-live",
            },
            status=201,
        )

    async def _find_memo_for_write(self, *, name: str, query: str):
        if name:
            return await asyncio.to_thread(self._memos.get, name)
        results = await asyncio.to_thread(self._memos.search, query, None, 3)
        if not results:
            return web.json_response({"error": "memo_not_found"}, status=404)
        if len(results) > 1:
            return web.json_response(
                {
                    "error": "memo_match_ambiguous",
                    "matches": [result.as_dict() for result in results],
                },
                status=409,
            )
        return await asyncio.to_thread(self._memos.get, results[0].memo.name)

    async def _propose_task_due_update(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        profile = str(body.get("profile") or "main").strip().lower() or "main"
        try:
            profile_host(profile)
        except CalendarAdapterError:
            return web.json_response({"error": "invalid_profile"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        task_title = " ".join(str(body.get("taskTitle") or "").split())
        collection_id = str(body.get("collectionId") or "").strip()
        due_date = str(body.get("dueDate") or "").strip()
        due_time = str(body.get("dueTime") or "10:00").strip() or "10:00"
        if not actor_id or not idempotency_key or not task_title:
            return web.json_response({"error": "task_update_missing_required_field"}, status=400)
        if not _valid_due(due_date, due_time):
            return web.json_response({"error": "task_update_invalid_due"}, status=400)
        try:
            tasks = await asyncio.to_thread(self._calendar_adapter.list_tasks, profile)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        matches = _match_active_tasks(tasks, task_title)
        if collection_id:
            matches = [task for task in matches if str(task.get("collection") or "") == collection_id]
        if not matches:
            return web.json_response({"error": "task_not_found"}, status=404)
        if len(matches) > 1:
            return web.json_response(
                {
                    "error": "task_match_ambiguous",
                    "matches": [task_payload(item, {}) for item in matches[:5]],
                },
                status=409,
            )
        task = matches[0]
        title = str(task.get("summary") or "Untitled task")
        payload = {
            "uid": str(task.get("uid") or ""),
            "collectionId": str(task.get("collection") or ""),
            "title": title,
            "memo": str(task.get("description") or ""),
            "dueDate": due_date,
            "dueTime": due_time,
            "priority": str(task.get("priority") or ""),
            "status": str(task.get("status") or ""),
        }
        try:
            actor = Actor("user", actor_id, "family" if profile == "family" else "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="calendar.tasks",
                    operation_type="update_due",
                    parameters={
                        "profile": profile,
                        "uid": payload["uid"],
                        "collectionId": payload["collectionId"],
                        "title": title,
                        "oldDue": str(task.get("due") or ""),
                        "oldDueTime": str(task.get("dueTime") or ""),
                        "newDue": due_date,
                        "newDueTime": due_time,
                    },
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        pending = PendingTaskDueUpdate(
            profile=profile,
            uid=payload["uid"],
            collection_id=payload["collectionId"],
            title=title,
            old_due=str(task.get("due") or ""),
            old_due_time=str(task.get("dueTime") or ""),
            new_due=due_date,
            new_due_time=due_time,
            payload=payload,
        )
        self._pending_task_due_updates[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "task": _pending_task_payload(pending),
                "source": "calendar-adapter-live",
            },
            status=201,
        )

    async def _propose_task_create(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        profile = str(body.get("profile") or "main").strip().lower() or "main"
        try:
            profile_host(profile)
        except CalendarAdapterError:
            return web.json_response({"error": "invalid_profile"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        title = " ".join(str(body.get("title") or "").split())
        due_date = str(body.get("dueDate") or "").strip()
        due_time = str(body.get("dueTime") or "10:00").strip() or "10:00"
        collection_id = str(body.get("collectionId") or "").strip()
        if not actor_id or not idempotency_key or not title:
            return web.json_response({"error": "task_create_missing_required_field"}, status=400)
        if not _valid_due(due_date, due_time):
            return web.json_response({"error": "task_create_invalid_due"}, status=400)
        payload = {
            "title": title,
            "memo": "",
            "dueDate": due_date,
            "dueTime": due_time,
            "priority": "",
        }
        if collection_id:
            payload["collectionId"] = collection_id
        try:
            actor = Actor("user", actor_id, "family" if profile == "family" else "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="calendar.tasks",
                    operation_type="create",
                    parameters={
                        "profile": profile,
                        "title": title,
                        "dueDate": due_date,
                        "dueTime": due_time,
                        "collectionId": collection_id,
                    },
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        pending = PendingTaskCreate(
            profile=profile,
            collection_id=collection_id,
            title=title,
            due=due_date,
            due_time=due_time,
            payload=payload,
        )
        self._pending_task_creates[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "task": _pending_task_create_payload(pending),
                "source": "calendar-adapter-live",
            },
            status=201,
        )

    async def _propose_task_action(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        profile = str(body.get("profile") or "main").strip().lower() or "main"
        try:
            profile_host(profile)
        except CalendarAdapterError:
            return web.json_response({"error": "invalid_profile"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        task_title = " ".join(str(body.get("taskTitle") or "").split())
        collection_id = str(body.get("collectionId") or "").strip()
        action = str(body.get("action") or "").strip().lower()
        if action not in {"complete", "delete", "reopen"}:
            return web.json_response({"error": "task_action_invalid_action"}, status=400)
        if not actor_id or not idempotency_key or not task_title:
            return web.json_response({"error": "task_action_missing_required_field"}, status=400)
        try:
            tasks = await asyncio.to_thread(self._calendar_adapter.list_tasks, profile)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        matches = _match_completed_tasks(tasks, task_title) if action == "reopen" else _match_active_tasks(tasks, task_title)
        if collection_id:
            matches = [task for task in matches if str(task.get("collection") or "") == collection_id]
        if not matches:
            return web.json_response({"error": "task_not_found"}, status=404)
        if len(matches) > 1:
            return web.json_response(
                {
                    "error": "task_match_ambiguous",
                    "matches": [task_payload(item, {}) for item in matches[:5]],
                },
                status=409,
            )
        task = matches[0]
        uid = str(task.get("uid") or "")
        collection_id = str(task.get("collection") or "")
        title = str(task.get("summary") or "Untitled task")
        payload = {
            "uid": uid,
            "collectionId": collection_id,
            "title": title,
            "memo": str(task.get("description") or ""),
            "dueDate": str(task.get("due") or ""),
            "dueTime": str(task.get("dueTime") or ""),
            "priority": str(task.get("priority") or ""),
            "status": _task_action_status(action, task),
        }
        try:
            actor = Actor("user", actor_id, "family" if profile == "family" else "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="calendar.tasks",
                    operation_type=action,
                    parameters={
                        "profile": profile,
                        "uid": uid,
                        "collectionId": collection_id,
                        "title": title,
                        "action": action,
                    },
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        pending = PendingTaskAction(
            profile=profile,
            action=action,
            uid=uid,
            collection_id=collection_id,
            title=title,
            due=str(task.get("due") or ""),
            due_time=str(task.get("dueTime") or ""),
            payload=payload,
        )
        self._pending_task_actions[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "task": _pending_task_action_payload(pending),
                "source": "calendar-adapter-live",
            },
            status=201,
        )

    async def _propose_event_create(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        profile = str(body.get("profile") or "main").strip().lower() or "main"
        try:
            profile_host(profile)
        except CalendarAdapterError:
            return web.json_response({"error": "invalid_profile"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        title = " ".join(str(body.get("title") or "").split())
        start_date = str(body.get("startDate") or "").strip()
        end_date = str(body.get("endDate") or start_date).strip() or start_date
        memo = str(body.get("memo") or "").strip()
        all_day = bool(body.get("allDay", True))
        collection_id = str(body.get("collectionId") or "").strip()
        if not collection_id and profile == "family":
            collection_id = "family:events"
        if not actor_id or not idempotency_key or not title or not start_date:
            return web.json_response({"error": "event_create_missing_required_field"}, status=400)
        if not _valid_date(start_date) or not _valid_date(end_date):
            return web.json_response({"error": "event_create_invalid_date"}, status=400)
        payload = {
            "title": title,
            "startDate": start_date,
            "endDate": end_date,
            "allDay": all_day,
            "memo": memo,
        }
        if collection_id:
            payload["collectionId"] = collection_id
        try:
            actor = Actor("user", actor_id, "family" if profile == "family" else "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="calendar.events",
                    operation_type="create",
                    parameters={
                        "profile": profile,
                        "title": title,
                        "startDate": start_date,
                        "endDate": end_date,
                        "allDay": all_day,
                        "memo": memo,
                        "collectionId": collection_id,
                    },
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        pending = PendingEventCreate(
            profile=profile,
            title=title,
            start_date=start_date,
            end_date=end_date,
            all_day=all_day,
            memo=memo,
            collection_id=collection_id,
            payload=payload,
        )
        self._pending_event_creates[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "event": _pending_event_create_payload(pending),
                "source": "calendar-adapter-live",
            },
            status=201,
        )

    async def _approve_confirmation(self, request: web.Request) -> web.Response:
        confirmation_id = request.match_info["confirmation_id"]
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        if not actor_id:
            return web.json_response({"error": "actor_id_required"}, status=400)
        confirmation = self._durable.get_confirmation(confirmation_id)
        if confirmation is None:
            return web.json_response({"error": "confirmation_not_found"}, status=404)
        operation = self._durable.get_operation(confirmation.operation_id)
        if operation is None:
            return web.json_response({"error": "operation_not_found"}, status=404)
        pending_update = self._pending_task_due_updates.get(operation.operation_id)
        pending_create = self._pending_task_creates.get(operation.operation_id)
        pending_action = self._pending_task_actions.get(operation.operation_id)
        pending_event_create = self._pending_event_creates.get(operation.operation_id)
        pending_memo_create = self._pending_memo_creates.get(operation.operation_id)
        pending_memo_delete = self._pending_memo_deletes.get(operation.operation_id)
        pending_memo_edit = self._pending_memo_edits.get(operation.operation_id)
        if (
            pending_update is None
            and pending_create is None
            and pending_action is None
            and pending_event_create is None
            and pending_memo_create is None
            and pending_memo_delete is None
            and pending_memo_edit is None
        ):
            return web.json_response({"error": "operation_payload_not_found"}, status=410)
        try:
            actor = Actor("user", actor_id, operation.actor.scope)
            self._durable.approve_confirmation(
                confirmation_id,
                actor=actor,
                normalized_operation_hash=operation.request_hash,
            )
            if pending_update is not None:
                result = await asyncio.to_thread(
                    self._calendar_adapter.update_task,
                    pending_update.profile,
                    pending_update.payload,
                )
                task = _pending_task_payload(pending_update)
                result_uid = str(result.get("uid") or pending_update.uid)
            elif pending_create is not None or pending_action is not None:
                if pending_create is not None:
                    result = await asyncio.to_thread(
                        self._calendar_adapter.create_task,
                        pending_create.profile,
                        pending_create.payload,
                    )
                    result_uid = str(result.get("uid") or "")
                    task = {**_pending_task_create_payload(pending_create), "uid": result_uid}
                else:
                    assert pending_action is not None
                    if pending_action.action == "delete":
                        result = await asyncio.to_thread(
                            self._calendar_adapter.delete_task,
                            pending_action.profile,
                            pending_action.uid,
                            pending_action.collection_id,
                        )
                        result_uid = str(result.get("uid") or pending_action.uid)
                    else:
                        result = await asyncio.to_thread(
                            self._calendar_adapter.update_task,
                            pending_action.profile,
                            pending_action.payload,
                        )
                        result_uid = str(result.get("uid") or pending_action.uid)
                    task = _pending_task_action_payload(pending_action)
            elif pending_event_create is not None:
                result = await asyncio.to_thread(
                    self._calendar_adapter.create_event,
                    pending_event_create.profile,
                    pending_event_create.payload,
                )
                result_uid = str(result.get("uid") or "")
                event = {**_pending_event_create_payload(pending_event_create), "uid": result_uid}
            else:
                if pending_memo_create is not None:
                    memo = await asyncio.to_thread(self._memos.create, pending_memo_create.content)
                    result_uid = memo.name
                    memo_payload = {"name": memo.name, "content": memo.content, "action": "create"}
                elif pending_memo_edit is not None:
                    memo = await asyncio.to_thread(self._memos.update, pending_memo_edit.name, pending_memo_edit.new_content)
                    result_uid = memo.name
                    memo_payload = _completed_memo_edit_payload(pending_memo_edit, memo.content)
                else:
                    assert pending_memo_delete is not None
                    await asyncio.to_thread(self._memos.delete, pending_memo_delete.name)
                    result_uid = pending_memo_delete.name
                    memo_payload = _pending_memo_delete_payload(pending_memo_delete)
            self._durable.complete_operation(operation.operation_id, result={"uid": result_uid})
            if pending_memo_create is None and pending_memo_delete is None and pending_memo_edit is None:
                await self._refresh_tasks()
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except CalendarAdapterError as exc:
            self._durable.fail_operation(operation.operation_id, error_code="calendar_adapter_error")
            return web.json_response({"error": str(exc)}, status=502)
        except (ValueError, MemosError) as exc:
            self._durable.fail_operation(operation.operation_id, error_code=str(exc))
            return _memos_error(exc)
        self._pending_task_due_updates.pop(operation.operation_id, None)
        self._pending_task_creates.pop(operation.operation_id, None)
        self._pending_task_actions.pop(operation.operation_id, None)
        self._pending_event_creates.pop(operation.operation_id, None)
        self._pending_memo_creates.pop(operation.operation_id, None)
        self._pending_memo_deletes.pop(operation.operation_id, None)
        self._pending_memo_edits.pop(operation.operation_id, None)
        response_payload = {
            "operationId": operation.operation_id,
            "confirmationId": confirmation_id,
            "status": "completed",
            "source": "memos-live"
            if pending_memo_create is not None or pending_memo_delete is not None or pending_memo_edit is not None
            else "calendar-adapter-live",
        }
        if pending_memo_create is not None or pending_memo_delete is not None or pending_memo_edit is not None:
            response_payload["memo"] = memo_payload
        elif pending_event_create is not None:
            response_payload["event"] = event
        else:
            response_payload["task"] = task
        return web.json_response(
            response_payload
        )

    async def _refresh_tasks(self) -> None:
        if self._task_refresh_callback is None:
            return
        try:
            await self._task_refresh_callback()
        except Exception:
            LOGGER.exception("Brain tool task refresh failed")

    def _with_weather(self, profile: str, bootstrap: Mapping[str, Any], days: list[date]) -> dict[str, Any]:
        payload = dict(bootstrap)
        try:
            weather = self._calendar_adapter.month_weather(
                profile,
                start=min(days).isoformat(),
                end=max(days).isoformat(),
            )
        except CalendarAdapterError:
            payload.setdefault("weather", [])
            return payload
        payload["weather"] = [dict(item) for item in weather.get("items", []) if isinstance(item, Mapping)]
        return payload


def today_payload(bootstrap: Mapping[str, Any], *, profile: str, current: date) -> dict[str, object]:
    collections = collections_by_id(bootstrap)
    events = [
        event_payload(item, collections)
        for item in items(bootstrap, "events")
        if item_date(item, "startDate") == current
    ]
    tasks = [
        task_payload(item, collections)
        for item in items(bootstrap, "tasks")
        if item_date(item, "due") == current and is_active_task(item)
    ]
    weather = weather_items_by_date(bootstrap).get(current)
    return {
        "date": current.isoformat(),
        "profile": profile,
        "events": events,
        "tasks": tasks,
        "weather": weather_payload(weather),
        "source": "calendar-adapter-live",
    }


def active_task_payloads(tasks: list[Mapping[str, Any]], *, collection_id: str = "") -> list[dict[str, object]]:
    active = [
        task_payload(item, {})
        for item in tasks
        if is_active_task(item) and (not collection_id or str(item.get("collection") or "") == collection_id)
    ]
    return sorted(
        active,
        key=lambda item: (
            str(item.get("due") or "9999-12-31"),
            str(item.get("title") or ""),
            str(item.get("uid") or ""),
        ),
    )


def completed_task_payloads(
    tasks: list[Mapping[str, Any]],
    *,
    collection_id: str = "",
    query: str = "",
    start: date | None = None,
    end: date | None = None,
    limit: int = 25,
) -> list[dict[str, object]]:
    normalized_query = _normalize_match_text(query)
    completed = [
        task_payload(item, {})
        for item in tasks
        if is_completed_task(item)
        and (not collection_id or str(item.get("collection") or "") == collection_id)
        and _matches_optional_query(item, normalized_query)
        and _within_optional_range(completed_task_date(item), start, end)
    ]
    completed.sort(
        key=lambda item: (
            str(item.get("title") or ""),
            str(item.get("uid") or ""),
        ),
    )
    completed.sort(key=lambda item: str(item.get("completedDate") or "0000-00-00"), reverse=True)
    return completed[: max(limit, 0)]


def event_payload(item: Mapping[str, Any], collections: Mapping[str, Mapping[str, Any]]) -> dict[str, object]:
    collection_id = str(item.get("collection") or "")
    collection = collections.get(collection_id, {})
    return {
        "uid": str(item.get("uid") or ""),
        "title": str(item.get("summary") or "Untitled event"),
        "date": str(item.get("startDate") or ""),
        "time": str(item.get("startTime") or ""),
        "collectionId": collection_id,
        "owner": str(collection.get("owner") or ""),
        "ownerLabel": str(collection.get("ownerLabel") or ""),
        "categories": [str(value) for value in item.get("categories", []) if str(value)],
    }


def task_payload(item: Mapping[str, Any], collections: Mapping[str, Mapping[str, Any]]) -> dict[str, object]:
    collection_id = str(item.get("collection") or "")
    collection = collections.get(collection_id, {})
    completed_value, completed_source = completed_task_value(item)
    return {
        "uid": str(item.get("uid") or ""),
        "title": str(item.get("summary") or "Untitled task"),
        "due": str(item.get("due") or ""),
        "dueTime": str(item.get("dueTime") or ""),
        "status": str(item.get("status") or ""),
        "completedDate": completed_value,
        "completedDateSource": completed_source,
        "priority": str(item.get("priority") or ""),
        "collectionId": collection_id,
        "owner": str(collection.get("owner") or ""),
        "ownerLabel": str(collection.get("ownerLabel") or ""),
    }


def weather_payload(weather: Mapping[str, Any] | None) -> dict[str, object]:
    if not weather:
        return {}
    return {
        "date": str(weather.get("date") or ""),
        "summary": weather_agenda_summary(weather),
        "condition": str(weather.get("condition") or weather.get("summary") or weather.get("weather") or ""),
        "minTemp": weather.get("minTemp", ""),
        "maxTemp": weather.get("maxTemp", ""),
    }


def collections_by_id(bootstrap: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("id") or ""): item
        for item in items(bootstrap, "collections")
        if str(item.get("id") or "")
    }


def items(bootstrap: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    return [item for item in bootstrap.get(name, []) if isinstance(item, Mapping)]


def item_date(item: Mapping[str, Any], key: str) -> date | None:
    try:
        raw = str(item.get(key) or "")
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def is_active_task(item: Mapping[str, Any]) -> bool:
    return bool(str(item.get("uid") or "")) and str(item.get("status") or "").upper() != "COMPLETED"


def is_completed_task(item: Mapping[str, Any]) -> bool:
    return bool(str(item.get("uid") or "")) and str(item.get("status") or "").upper() == "COMPLETED"


def completed_task_date(item: Mapping[str, Any]) -> date | None:
    value, _source = completed_task_value(item)
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def completed_task_value(item: Mapping[str, Any]) -> tuple[str, str]:
    for key in ("completed", "completedAt", "completedDate", "lastModified", "updated", "due"):
        raw = str(item.get(key) or "").strip()
        if raw:
            return raw[:10], key
    return "", ""


def _valid_due(due_date: str, due_time: str) -> bool:
    try:
        datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    return True


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _match_active_tasks(tasks: list[Mapping[str, Any]], query: str) -> list[Mapping[str, Any]]:
    normalized_query = _normalize_match_text(query)
    active = [item for item in tasks if is_active_task(item)]
    exact = [
        item
        for item in active
        if _normalize_match_text(str(item.get("summary") or "")) == normalized_query
    ]
    if exact:
        return exact
    return [
        item
        for item in active
        if normalized_query in _normalize_match_text(str(item.get("summary") or ""))
    ]


def _match_completed_tasks(tasks: list[Mapping[str, Any]], query: str) -> list[Mapping[str, Any]]:
    normalized_query = _normalize_match_text(query)
    completed = [item for item in tasks if is_completed_task(item)]
    exact = [
        item
        for item in completed
        if _normalize_match_text(str(item.get("summary") or "")) == normalized_query
    ]
    if exact:
        return exact
    return [
        item
        for item in completed
        if normalized_query in _normalize_match_text(str(item.get("summary") or ""))
    ]


def _task_action_status(action: str, task: Mapping[str, Any]) -> str:
    if action == "complete":
        return "COMPLETED"
    if action == "reopen":
        return "NEEDS-ACTION"
    return str(task.get("status") or "")


def _normalize_match_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _matches_optional_query(item: Mapping[str, Any], normalized_query: str) -> bool:
    if not normalized_query:
        return True
    haystack = " ".join(
        (
            str(item.get("summary") or ""),
            str(item.get("description") or ""),
            " ".join(str(value) for value in item.get("categories", []) if str(value)),
        )
    )
    return normalized_query in _normalize_match_text(haystack)


def _within_optional_range(value: date | None, start: date | None, end: date | None) -> bool:
    if value is None:
        return start is None and end is None
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def _pending_task_payload(pending: PendingTaskDueUpdate) -> dict[str, object]:
    return {
        "uid": pending.uid,
        "collectionId": pending.collection_id,
        "title": pending.title,
        "oldDue": pending.old_due,
        "oldDueTime": pending.old_due_time,
        "newDue": pending.new_due,
        "newDueTime": pending.new_due_time,
    }


def _pending_task_create_payload(pending: PendingTaskCreate) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": pending.title,
        "due": pending.due,
        "dueTime": pending.due_time,
    }
    if pending.collection_id:
        payload["collectionId"] = pending.collection_id
    return payload


def _pending_task_action_payload(pending: PendingTaskAction) -> dict[str, object]:
    return {
        "uid": pending.uid,
        "collectionId": pending.collection_id,
        "title": pending.title,
        "due": pending.due,
        "dueTime": pending.due_time,
        "action": pending.action,
    }


def _pending_event_create_payload(pending: PendingEventCreate) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": pending.title,
        "startDate": pending.start_date,
        "endDate": pending.end_date,
        "allDay": pending.all_day,
        "memo": pending.memo,
    }
    if pending.collection_id:
        payload["collectionId"] = pending.collection_id
    return payload


def _pending_memo_create_payload(pending: PendingMemoCreate) -> dict[str, object]:
    return {"content": pending.content}


def _pending_memo_delete_payload(pending: PendingMemoDelete) -> dict[str, object]:
    return {"name": pending.name, "content": pending.content, "action": "delete"}


def _pending_memo_edit_payload(pending: PendingMemoEdit) -> dict[str, object]:
    return {
        "name": pending.name,
        "oldContent": pending.old_content,
        "newContent": pending.new_content,
        "action": "edit",
    }


def _completed_memo_edit_payload(pending: PendingMemoEdit, content: str) -> dict[str, object]:
    return {**_pending_memo_edit_payload(pending), "content": content}


def _profile(request: web.Request) -> str:
    profile = request.query.get("profile", "main").strip().lower() or "main"
    try:
        profile_host(profile)
    except CalendarAdapterError as exc:
        raise web.HTTPBadRequest(text='{"error": "invalid_profile"}', content_type="application/json") from exc
    return profile


def _request_date(request: web.Request, *, default: date) -> date:
    raw = request.query.get("date", "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise web.HTTPBadRequest(text='{"error": "invalid_date"}', content_type="application/json") from exc


def _optional_request_date(request: web.Request, name: str) -> date | None:
    raw = request.query.get(name, "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise web.HTTPBadRequest(text='{"error": "invalid_date"}', content_type="application/json") from exc


def _limit(request: web.Request, *, default: int) -> int:
    raw = request.query.get("limit", str(default)).strip() or str(default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise web.HTTPBadRequest(text='{"error": "invalid_limit"}', content_type="application/json") from exc
    return value


def _memos_error(error: ValueError | MemosError) -> web.Response:
    code = error.code if isinstance(error, MemosError) else str(error)
    if code == "memos_not_found":
        status = 404
    elif code == "memos_search_disabled":
        status = 503
    elif isinstance(error, MemosError):
        status = 502
    else:
        status = 400
    return web.json_response({"error": code}, status=status)


def _document_error(error: DocumentIntakeError) -> web.Response:
    status = 503 if error.code == "paperless_not_configured" else 400
    return web.json_response({"error": error.code}, status=status)
