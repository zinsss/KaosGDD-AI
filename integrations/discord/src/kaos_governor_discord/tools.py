from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from kaos_governor import Actor, DurableGovernorError, MemoryDurableGovernorStore, OperationRequest
from kaos_governor.calendar import CalendarAdapterClient, CalendarAdapterError, profile_host, render_month_png
from kaos_governor.documents import DocumentIntakeError, PaperlessDocumentService
from kaos_governor.memos import MemosError, MemosService

from .calendar import month_markers, visible_month_grid_range, weather_agenda_summary, weather_items_by_date
from .tasks import TASK_PRIORITIES, is_supplies_collection, normalize_supplies_due, validate_edit_due


LOGGER = logging.getLogger(__name__)
SECOND_LOOK_RATE_LIMIT_WINDOW = timedelta(minutes=10)
SECOND_LOOK_RATE_LIMIT_COUNT = 6
SECOND_LOOK_RESPONSE_CACHE_TTL = timedelta(minutes=30)
KST = timezone(timedelta(hours=9), "KST")


def kst_today(now: datetime | None = None) -> date:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(KST).date()


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
    memo: str
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
class PendingTaskEdit:
    profile: str
    uid: str
    collection_id: str
    old_title: str
    new_title: str
    old_memo: str
    new_memo: str
    old_due: str
    old_due_time: str
    new_due: str
    new_due_time: str
    old_priority: str
    new_priority: str
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


@dataclass(frozen=True)
class PendingDocumentMetadata:
    document_id: int
    old_title: str
    title: str
    tags: tuple[str, ...]
    payload: dict[str, Any]


@dataclass
class SecondLookStatus:
    request_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    rate_limited_count: int = 0
    last_request_at: str = ""
    last_completed_at: str = ""
    last_failed_at: str = ""
    last_job_id: str = ""
    last_status: str = ""
    last_model: str = ""
    last_error: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "requestCount": self.request_count,
            "completedCount": self.completed_count,
            "failedCount": self.failed_count,
            "rateLimitedCount": self.rate_limited_count,
            "lastRequestAt": self.last_request_at,
            "lastCompletedAt": self.last_completed_at,
            "lastFailedAt": self.last_failed_at,
            "lastJobId": self.last_job_id,
            "lastStatus": self.last_status,
            "lastModel": self.last_model,
            "lastError": self.last_error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SecondLookStatus":
        return cls(
            request_count=_status_int(payload, "requestCount"),
            completed_count=_status_int(payload, "completedCount"),
            failed_count=_status_int(payload, "failedCount"),
            rate_limited_count=_status_int(payload, "rateLimitedCount"),
            last_request_at=str(payload.get("lastRequestAt") or ""),
            last_completed_at=str(payload.get("lastCompletedAt") or ""),
            last_failed_at=str(payload.get("lastFailedAt") or ""),
            last_job_id=str(payload.get("lastJobId") or ""),
            last_status=str(payload.get("lastStatus") or ""),
            last_model=str(payload.get("lastModel") or ""),
            last_error=str(payload.get("lastError") or ""),
        )


@dataclass(frozen=True)
class ImagingSecondLookConfig:
    url: str = ""
    token: str = ""
    timeout_seconds: int = 180

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)


class ImagingSecondLookClient:
    def __init__(self, config: ImagingSecondLookConfig) -> None:
        self.config = config

    async def second_look(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("imaging_second_look_not_configured")
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {"Authorization": f"Bearer {self.config.token}"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            try:
                async with session.post(self.config.url, json=dict(payload)) as response:
                    data = await response.json()
                    if response.status >= 400:
                        error = str(data.get("error") or f"http_{response.status}") if isinstance(data, Mapping) else f"http_{response.status}"
                        raise RuntimeError(error)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise RuntimeError("imaging_second_look_timed_out") from exc
            except aiohttp.ClientError as exc:
                raise RuntimeError("imaging_second_look_request_failed") from exc
            except ValueError as exc:
                raise RuntimeError("imaging_second_look_response_not_json") from exc
        if not isinstance(data, Mapping):
            raise RuntimeError("imaging_second_look_response_not_object")
        return _normalize_second_look_provider_response(data)


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
        calendar_refresh_callback: Callable[[], Awaitable[None]] | None = None,
        import_status_provider: Callable[[], Mapping[str, object]] | None = None,
        import_items_provider: Callable[[], list[Mapping[str, object]]] | None = None,
        mail_messages_provider: Callable[[int], Mapping[str, object]] | None = None,
        today_provider: Callable[[], date] | None = None,
        durable_store: MemoryDurableGovernorStore | None = None,
        imaging_second_look: ImagingSecondLookClient | None = None,
        second_look_status_path: Path | None = None,
        second_look_status_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._governor_api_token = governor_api_token
        self._calendar_adapter = calendar_adapter
        self._memos = memos
        self._paperless = paperless
        self._calendar_refresh_callback = calendar_refresh_callback or task_refresh_callback
        self._import_status_provider = import_status_provider
        self._import_items_provider = import_items_provider
        self._mail_messages_provider = mail_messages_provider
        self._today_provider = today_provider or kst_today
        self._durable = durable_store or MemoryDurableGovernorStore()
        self._imaging_second_look_client = imaging_second_look or ImagingSecondLookClient(ImagingSecondLookConfig())
        self._second_look_rate: dict[str, list[datetime]] = {}
        self._second_look_response_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._second_look_status_path = second_look_status_path
        self._second_look_status_callback = second_look_status_callback
        self._second_look_status_refresh_task: asyncio.Task | None = None
        self._second_look_status = self._load_second_look_status()
        self._pending_task_due_updates: dict[str, PendingTaskDueUpdate] = {}
        self._pending_task_creates: dict[str, PendingTaskCreate] = {}
        self._pending_task_actions: dict[str, PendingTaskAction] = {}
        self._pending_task_edits: dict[str, PendingTaskEdit] = {}
        self._pending_event_creates: dict[str, PendingEventCreate] = {}
        self._pending_memo_creates: dict[str, PendingMemoCreate] = {}
        self._pending_memo_deletes: dict[str, PendingMemoDelete] = {}
        self._pending_memo_edits: dict[str, PendingMemoEdit] = {}
        self._pending_document_metadata: dict[str, PendingDocumentMetadata] = {}
        self._runner: web.AppRunner | None = None

    def application(self) -> web.Application:
        app = web.Application(client_max_size=32 * 1024 * 1024)
        app.middlewares.append(self._auth_middleware)
        app.router.add_get("/tools/today", self._today)
        app.router.add_get("/tools/events/upcoming", self._upcoming_events)
        app.router.add_get("/tools/calendar/week", self._calendar_week)
        app.router.add_get("/tools/calendar/month-image", self._calendar_month_image)
        app.router.add_get("/tools/imports/recent", self._recent_imports)
        app.router.add_get("/tools/mail/naver/list", self._list_naver_mail)
        app.router.add_get("/tools/tasks/active", self._active_tasks)
        app.router.add_get("/tools/tasks/completed", self._completed_tasks)
        app.router.add_get("/tools/memos/list", self._list_memos)
        app.router.add_get("/tools/memos/search", self._search_memos)
        app.router.add_get("/tools/memos/{memo_id}", self._get_memo)
        app.router.add_post("/tools/memos/create/proposals", self._propose_memo_create)
        app.router.add_post("/tools/memos/edit/proposals", self._propose_memo_edit)
        app.router.add_post("/tools/memos/delete/proposals", self._propose_memo_delete)
        app.router.add_get("/tools/documents/list", self._list_documents)
        app.router.add_get("/tools/documents/search", self._search_documents)
        app.router.add_get("/tools/documents/{document_id}", self._get_document)
        app.router.add_get("/tools/documents/{document_id}/tag-context", self._get_document_tag_context)
        app.router.add_post("/tools/documents/{document_id}/metadata/proposals", self._propose_document_metadata)
        app.router.add_post("/tools/documents/{document_id}/tags/proposals", self._propose_document_tags)
        app.router.add_post("/tools/tasks/action/proposals", self._propose_task_action)
        app.router.add_post("/tools/tasks/edit/proposals", self._propose_task_edit)
        app.router.add_post("/tools/tasks/create/proposals", self._propose_task_create)
        app.router.add_post("/tools/tasks/update-due/proposals", self._propose_task_due_update)
        app.router.add_post("/tools/events/create/proposals", self._propose_event_create)
        app.router.add_post("/tools/imaging/second-look", self._imaging_second_look)
        app.router.add_get("/tools/imaging/second-look/status", self._imaging_second_look_status)
        app.router.add_post("/tools/confirmations/{confirmation_id}/approve", self._approve_confirmation)
        return app

    async def start(self) -> None:
        self._runner = web.AppRunner(self.application(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self._host, self._port).start()

    async def stop(self) -> None:
        if self._second_look_status_refresh_task is not None:
            self._second_look_status_refresh_task.cancel()
            try:
                await self._second_look_status_refresh_task
            except asyncio.CancelledError:
                pass
            self._second_look_status_refresh_task = None
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
        city = str(request.query.get("city") or "").strip()
        days = [current]
        try:
            bootstrap = await asyncio.to_thread(self._calendar_adapter.bootstrap, profile)
            bootstrap = await asyncio.to_thread(self._with_weather, profile, bootstrap, days, city=city)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        return web.json_response(today_payload(bootstrap, profile=profile, current=current))

    async def _upcoming_events(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        current = _request_date(request, default=self._today_provider())
        try:
            days = int(request.query.get("days", "3").strip() or "3")
        except ValueError as exc:
            raise web.HTTPBadRequest(text='{"error": "invalid_days"}', content_type="application/json") from exc
        days = min(max(days, 1), 14)
        try:
            bootstrap = await asyncio.to_thread(self._calendar_adapter.bootstrap, profile)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        events = upcoming_event_payloads(bootstrap, profile=profile, current=current, days=days)
        return web.json_response(
            {
                "date": current.isoformat(),
                "profile": profile,
                "days": days,
                "count": len(events),
                "events": events,
                "source": "calendar-adapter-live",
            }
        )

    async def _calendar_week(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        current = _request_date(request, default=self._today_provider())
        try:
            days = int(request.query.get("days", "7").strip() or "7")
        except ValueError as exc:
            raise web.HTTPBadRequest(text='{"error": "invalid_days"}', content_type="application/json") from exc
        days = min(max(days, 1), 14)
        day_values = [current + timedelta(days=offset) for offset in range(days)]
        try:
            bootstrap = await asyncio.to_thread(self._calendar_adapter.bootstrap, profile)
            bootstrap = await asyncio.to_thread(self._with_weather, profile, bootstrap, day_values)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        return web.json_response(calendar_week_payload(bootstrap, profile=profile, current=current, days=days))

    async def _calendar_month_image(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        current = _request_date(request, default=self._today_provider())
        year = _optional_int_query(request, "year", current.year)
        month = _optional_int_query(request, "month", current.month)
        try:
            visible_month = date(year, month, 1)
        except ValueError as exc:
            raise web.HTTPBadRequest(text='{"error": "invalid_month"}', content_type="application/json") from exc
        try:
            bootstrap = await asyncio.to_thread(self._calendar_adapter.bootstrap, profile)
            start, end = visible_month_grid_range(visible_month.year, visible_month.month)
            day_values = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
            bootstrap = await asyncio.to_thread(self._with_weather, profile, bootstrap, day_values)
            png = await asyncio.to_thread(
                render_month_png,
                year=visible_month.year,
                month=visible_month.month,
                today=current,
                markers=month_markers(bootstrap),
            )
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        return web.json_response(
            {
                "date": current.isoformat(),
                "profile": profile,
                "year": visible_month.year,
                "month": visible_month.month,
                "filename": f"calendar-{visible_month.year}-{visible_month.month:02d}.png",
                "contentType": "image/png",
                "contentBase64": base64.b64encode(png).decode("ascii"),
                "source": "calendar-render-live",
            }
        )

    async def _recent_imports(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        current = _request_date(request, default=self._today_provider())
        status = self._import_status_provider() if self._import_status_provider is not None else {}
        summary_imports = _recent_import_payloads(status)
        detailed_imports = self._recent_import_detail_payloads()
        imports = _merge_recent_import_payloads(detailed_imports, summary_imports)
        return web.json_response(
            {
                "date": current.isoformat(),
                "profile": profile,
                "count": len(imports),
                "imports": imports,
                "source": "governor-runtime-items" if detailed_imports else "governor-runtime-status",
            }
        )

    async def _list_naver_mail(self, request: web.Request) -> web.Response:
        profile = _profile(request)
        current = _request_date(request, default=self._today_provider())
        limit = _limit(request, default=50)
        if self._mail_messages_provider is None:
            return web.json_response({"error": "mail_list_disabled"}, status=503)
        try:
            payload = await asyncio.to_thread(self._mail_messages_provider, limit)
        except Exception as exc:
            LOGGER.warning("Naver mail list failed: %s", exc)
            return web.json_response({"error": "mail_list_failed"}, status=502)
        messages = payload.get("messages") if isinstance(payload, Mapping) else None
        normalized = [_normalize_mail_list_item(item) for item in messages if isinstance(item, Mapping)] if isinstance(messages, list) else []
        return web.json_response(
            {
                "date": current.isoformat(),
                "profile": profile,
                "count": len(normalized),
                "totalCount": len(normalized),
                "mailboxCount": int(payload.get("mailboxCount") or 0) if isinstance(payload, Mapping) else 0,
                "folders": list(payload.get("folders") or []) if isinstance(payload, Mapping) else [],
                "messages": normalized,
                "source": "naver-imap-live",
            }
        )

    def _recent_import_detail_payloads(self) -> list[dict[str, object]]:
        if self._import_items_provider is None:
            return []
        try:
            rows = self._import_items_provider()
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            LOGGER.warning("Detailed import provider failed: %s", exc)
            return []
        if not isinstance(rows, list):
            return []
        return [_normalize_recent_import_item(item) for item in rows if isinstance(item, Mapping)]

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
            page = await asyncio.to_thread(self._memos.search_page, query, tags or None, limit)
        except (ValueError, MemosError) as exc:
            return _memos_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain Memos search failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response({**page.as_dict(), "source": "memos-live"})

    async def _list_memos(self, request: web.Request) -> web.Response:
        if not self._memos.config.enabled:
            return web.json_response({"error": "memos_search_disabled"}, status=503)
        limit = _limit(request, default=20)
        try:
            page = await asyncio.to_thread(self._memos.list_page, limit=limit)
        except (ValueError, MemosError) as exc:
            return _memos_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain Memos list failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response({**page.as_dict(), "source": "memos-live"})

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
        page_number = _optional_int_query(request, "page", 1)
        try:
            page = await asyncio.to_thread(self._paperless.search_page, query, limit=limit, page=page_number)
        except DocumentIntakeError as exc:
            return _document_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain document search failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response({**page.as_dict(), "source": "paperless-live"})

    async def _list_documents(self, request: web.Request) -> web.Response:
        limit = _limit(request, default=20)
        page_number = _optional_int_query(request, "page", 1)
        try:
            page = await asyncio.to_thread(self._paperless.list_page, limit=limit, page=page_number)
        except DocumentIntakeError as exc:
            return _document_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain document list failure")
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

    async def _get_document_tag_context(self, request: web.Request) -> web.Response:
        try:
            document, tags = await asyncio.gather(
                asyncio.to_thread(self._paperless.get, request.match_info["document_id"]),
                asyncio.to_thread(self._paperless.list_tags),
            )
        except DocumentIntakeError as exc:
            return _document_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Brain document tag-context failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response(
            {
                "document": _document_tag_context_document_payload(document.as_dict()),
                "availableTags": [tag.as_dict() for tag in tags],
                "source": "paperless-live",
            }
        )

    async def _propose_document_metadata(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        title = " ".join(str(body.get("title") or "").split())
        tags = _normalized_tags(body.get("tags") or [])
        if not actor_id or not idempotency_key or not title:
            return web.json_response({"error": "document_metadata_missing_required_field"}, status=400)
        try:
            proposal_payload = await asyncio.to_thread(
                self._paperless.metadata_proposal,
                request.match_info["document_id"],
                title=title,
                tags=tags,
            )
            proposal = proposal_payload["proposal"]
            actor = Actor("user", actor_id, "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="documents",
                    operation_type="update_metadata",
                    parameters={
                        "documentId": int(proposal["id"]),
                        "oldTitle": str(proposal["oldTitle"]),
                        "title": str(proposal["title"]),
                        "tags": list(proposal["tags"]),
                    },
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except DocumentIntakeError as exc:
            return _document_error(exc)
        pending = PendingDocumentMetadata(
            document_id=int(proposal["id"]),
            old_title=str(proposal["oldTitle"]),
            title=str(proposal["title"]),
            tags=tuple(str(tag) for tag in proposal["tags"]),
            payload={
                "documentId": int(proposal["id"]),
                "title": str(proposal["title"]),
                "tags": tuple(str(tag) for tag in proposal["tags"]),
            },
        )
        self._pending_document_metadata[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "document": _pending_document_metadata_payload(pending),
                "source": "paperless-live",
            },
            status=201,
        )

    async def _propose_document_tags(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)
        actor_id = str(body.get("actorId") or "").strip()
        idempotency_key = str(body.get("idempotencyKey") or "").strip()
        suggested_tags = _normalized_tags(body.get("tags") or [])
        if not actor_id or not idempotency_key or not suggested_tags:
            return web.json_response({"error": "document_tags_missing_required_field"}, status=400)
        try:
            proposal_payload = await asyncio.to_thread(
                self._paperless.metadata_proposal,
                request.match_info["document_id"],
                tags=suggested_tags,
            )
            proposal = proposal_payload["proposal"]
            actor = Actor("user", actor_id, "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="documents",
                    operation_type="update_tags",
                    parameters={
                        "documentId": int(proposal["id"]),
                        "oldTitle": str(proposal["oldTitle"]),
                        "title": str(proposal["title"]),
                        "tags": list(proposal["tags"]),
                        "suggestedTags": list(suggested_tags),
                        "ignoredTags": [],
                    },
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except DocumentIntakeError as exc:
            return _document_error(exc)
        pending = PendingDocumentMetadata(
            document_id=int(proposal["id"]),
            old_title=str(proposal["oldTitle"]),
            title=str(proposal["title"]),
            tags=tuple(str(tag) for tag in proposal["tags"]),
            payload={
                "documentId": int(proposal["id"]),
                "title": str(proposal["title"]),
                "tags": tuple(str(tag) for tag in proposal["tags"]),
            },
        )
        self._pending_document_metadata[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "document": _pending_document_metadata_payload(pending),
                "suggestedTags": list(suggested_tags),
                "ignoredTags": [],
                "source": "paperless-live",
            },
            status=201,
        )

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

    async def _imaging_second_look(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, Mapping):
            return web.json_response({"error": "invalid_json"}, status=400)

        error = _validate_second_look_request(body)
        if error:
            return web.json_response({"error": error}, status=400)

        request_id = str(body["requestId"]).strip()
        job_id = _second_look_job_id(request_id)
        source = str(body.get("source") or "").strip()
        parameters = _second_look_operation_parameters(body)
        try:
            operation, created = self._durable.start_operation(
                OperationRequest(
                    actor=Actor(actor_type="service", actor_id=source, scope="clinic"),
                    idempotency_key=request_id,
                    tool_name="imaging.second-look",
                    operation_type="temporary-review",
                    parameters=parameters,
                )
            )
        except DurableGovernorError as exc:
            if str(exc) == "idempotency_key_conflict":
                return web.json_response({"jobId": job_id, "error": "idempotency_key_conflict"}, status=409)
            return web.json_response({"jobId": job_id, "error": str(exc)}, status=400)

        if not created:
            if operation.status == "completed":
                cached = self._second_look_cached_response(operation.operation_id)
                if cached is not None:
                    return web.json_response(cached)
                return web.json_response(
                    {"jobId": job_id, "error": "imaging_second_look_result_expired"},
                    status=409,
                )
            return web.json_response(
                {"jobId": job_id, "error": f"imaging_second_look_operation_{operation.status}"},
                status=409,
            )

        self._record_second_look_request(job_id)
        self._durable.record_audit(
            actor=operation.actor,
            event_type="imaging.second-look.request",
            outcome="accepted",
            operation_id=operation.operation_id,
            tool_name=operation.tool_name,
            idempotency_key=operation.idempotency_key,
            request_hash=operation.request_hash,
            payload=parameters,
        )
        if self._second_look_rate_limited(source):
            self._durable.fail_operation(operation.operation_id, error_code="rate_limited")
            self._record_second_look_failure(job_id, "imaging_second_look_rate_limited", rate_limited=True)
            self._schedule_second_look_status_refresh()
            return web.json_response({"jobId": job_id, "error": "imaging_second_look_rate_limited"}, status=429)

        if self._imaging_second_look_client.config.enabled:
            try:
                provider_payload = await self._imaging_second_look_client.second_look(body)
            except RuntimeError as exc:
                self._durable.fail_operation(
                    operation.operation_id,
                    error_code=_second_look_error_code(str(exc)),
                )
                self._record_second_look_failure(job_id, str(exc))
                self._schedule_second_look_status_refresh()
                return web.json_response({"error": str(exc)}, status=502)
            response_payload = {"jobId": job_id, **provider_payload}
            self._complete_second_look_operation(operation.operation_id, response_payload)
            self._schedule_second_look_status_refresh()
            return web.json_response(response_payload)
        modality = str(body.get("modality") or "").strip().upper()
        ai_domain = str(body.get("aiDomain") or "").strip().lower()
        question = " ".join(str(body.get("question") or "").split())
        response_payload = {
            "jobId": job_id,
            "status": "completed",
            "result": {
                "summary": "AI second-look model is not connected yet. No clinical image opinion was generated.",
                "checklist": [
                    "Request accepted from KaosAIO for temporary review only.",
                    f"Modality: {modality or 'unknown'}; domain: {ai_domain or 'unknown'}.",
                    "Rendered preview image was received and discarded after request validation.",
                ],
                "cautions": [
                    "No DICOM, Orthanc, PACS, or AIO report data was modified.",
                    "This placeholder is not a diagnostic interpretation.",
                ],
                "recommendation": question or "Connect the approved KaosAI imaging model before using second-look output.",
                "disclaimer": "AI 보조 검토입니다. 최종 판단은 진료자가 합니다.",
                "model": "not-connected",
            },
        }
        self._complete_second_look_operation(operation.operation_id, response_payload)
        self._schedule_second_look_status_refresh()
        return web.json_response(response_payload)

    def _second_look_rate_limited(self, source: str) -> bool:
        now = datetime.now()
        cutoff = now - SECOND_LOOK_RATE_LIMIT_WINDOW
        recent = [timestamp for timestamp in self._second_look_rate.get(source, []) if timestamp >= cutoff]
        if len(recent) >= SECOND_LOOK_RATE_LIMIT_COUNT:
            self._second_look_rate[source] = recent
            return True
        recent.append(now)
        self._second_look_rate[source] = recent
        return False

    def _second_look_cached_response(self, operation_id: str) -> dict[str, Any] | None:
        cached = self._second_look_response_cache.get(operation_id)
        if cached is None:
            return None
        created_at, payload = cached
        if datetime.now() - created_at > SECOND_LOOK_RESPONSE_CACHE_TTL:
            self._second_look_response_cache.pop(operation_id, None)
            return None
        return dict(payload)

    def _complete_second_look_operation(self, operation_id: str, response_payload: Mapping[str, Any]) -> None:
        self._second_look_response_cache[operation_id] = (datetime.now(), dict(response_payload))
        self._durable.complete_operation(
            operation_id,
            result=_second_look_result_audit_payload(response_payload),
        )
        self._record_second_look_completion(response_payload)

    async def _imaging_second_look_status(self, request: web.Request) -> web.Response:
        return web.json_response({"secondLook": self._second_look_status.as_dict()})

    def _record_second_look_request(self, job_id: str) -> None:
        self._second_look_status.request_count += 1
        self._second_look_status.last_request_at = _second_look_now_text()
        self._second_look_status.last_job_id = job_id
        self._second_look_status.last_status = "accepted"
        self._save_second_look_status()

    def _record_second_look_completion(self, response_payload: Mapping[str, Any]) -> None:
        result = response_payload.get("result")
        model = str(result.get("model") or "").strip() if isinstance(result, Mapping) else ""
        self._second_look_status.completed_count += 1
        self._second_look_status.last_completed_at = _second_look_now_text()
        self._second_look_status.last_job_id = str(response_payload.get("jobId") or "").strip()
        self._second_look_status.last_status = str(response_payload.get("status") or "completed").strip() or "completed"
        self._second_look_status.last_model = model
        self._second_look_status.last_error = ""
        self._save_second_look_status()

    def _record_second_look_failure(self, job_id: str, error: str, *, rate_limited: bool = False) -> None:
        self._second_look_status.failed_count += 1
        if rate_limited:
            self._second_look_status.rate_limited_count += 1
        self._second_look_status.last_failed_at = _second_look_now_text()
        self._second_look_status.last_job_id = job_id
        self._second_look_status.last_status = "failed"
        self._second_look_status.last_error = error[:160]
        self._save_second_look_status()

    def _load_second_look_status(self) -> SecondLookStatus:
        if self._second_look_status_path is None:
            return SecondLookStatus()
        try:
            raw = json.loads(self._second_look_status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SecondLookStatus()
        status = raw.get("secondLook") if isinstance(raw, Mapping) else None
        if not isinstance(status, Mapping):
            return SecondLookStatus()
        return SecondLookStatus.from_dict(status)

    def _save_second_look_status(self) -> None:
        if self._second_look_status_path is None:
            return
        payload = {"secondLook": self._second_look_status.as_dict()}
        try:
            self._second_look_status_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._second_look_status_path.with_suffix(f"{self._second_look_status_path.suffix}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(self._second_look_status_path)
        except OSError:
            LOGGER.exception("Failed to persist second-look status")

    def _schedule_second_look_status_refresh(self) -> None:
        if self._second_look_status_callback is None:
            return
        if self._second_look_status_refresh_task is not None and not self._second_look_status_refresh_task.done():
            return
        self._second_look_status_refresh_task = asyncio.create_task(
            self._run_second_look_status_refresh(),
            name="governor-second-look-status-refresh",
        )

    async def _run_second_look_status_refresh(self) -> None:
        if self._second_look_status_callback is None:
            return
        try:
            await self._second_look_status_callback()
        except Exception:
            LOGGER.exception("Failed to refresh second-look service status")

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
        if profile == "supplies" or is_supplies_collection(collection_id):
            return web.json_response({"error": "supplies_due_not_allowed"}, status=400)
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
        memo = str(body.get("memo") or "").strip()
        due_date = str(body.get("dueDate") or "").strip()
        due_time = str(body.get("dueTime") or ("10:00" if due_date else "")).strip()
        collection_id = str(body.get("collectionId") or "").strip()
        if not actor_id or not idempotency_key or not title:
            return web.json_response({"error": "task_create_missing_required_field"}, status=400)
        allow_empty_due = not due_date and not due_time
        if not allow_empty_due and not _valid_due(due_date, due_time):
            return web.json_response({"error": "task_create_invalid_due"}, status=400)
        payload = {
            "title": title,
            "memo": memo,
            "dueDate": due_date,
            "dueTime": due_time,
            "priority": "",
        }
        if collection_id:
            payload["collectionId"] = collection_id
        payload = normalize_supplies_due(payload, collection_id=collection_id or profile)
        due_date = str(payload.get("dueDate") or "")
        due_time = str(payload.get("dueTime") or "")
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
                        "memo": memo,
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
            memo=memo,
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
        requested_uid = str(body.get("uid") or "").strip()
        task_title = " ".join(str(body.get("taskTitle") or "").split())
        collection_id = str(body.get("collectionId") or "").strip()
        action = str(body.get("action") or "").strip().lower()
        if action not in {"complete", "delete", "reopen"}:
            return web.json_response({"error": "task_action_invalid_action"}, status=400)
        if not actor_id or not idempotency_key or (not requested_uid and not task_title):
            return web.json_response({"error": "task_action_missing_required_field"}, status=400)
        try:
            tasks = await asyncio.to_thread(self._calendar_adapter.list_tasks, profile)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        if requested_uid:
            candidates = [item for item in tasks if is_completed_task(item)] if action == "reopen" else [item for item in tasks if is_active_task(item)]
            matches = [task for task in candidates if str(task.get("uid") or "") == requested_uid]
        else:
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
        payload = normalize_supplies_due(payload, collection_id=collection_id or profile)
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

    async def _propose_task_edit(self, request: web.Request) -> web.Response:
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
        uid = str(body.get("uid") or "").strip()
        task_title = " ".join(str(body.get("taskTitle") or "").split())
        collection_id = str(body.get("collectionId") or "").strip()
        new_title = " ".join(str(body.get("title") or "").split())
        new_memo = str(body.get("memo") or "").strip()
        due_date = str(body.get("dueDate") or "").strip()
        due_time = str(body.get("dueTime") or "").strip()
        priority = str(body.get("priority") or "").strip()
        if not actor_id or not idempotency_key or not new_title or (not uid and not task_title):
            return web.json_response({"error": "task_edit_missing_required_field"}, status=400)
        try:
            tasks = await asyncio.to_thread(self._calendar_adapter.list_tasks, profile)
        except CalendarAdapterError as exc:
            return web.json_response({"error": str(exc)}, status=502)
        if uid:
            matches = [task for task in tasks if is_active_task(task) and str(task.get("uid") or "") == uid]
        else:
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
        uid = str(task.get("uid") or "")
        collection_id = str(task.get("collection") or "")
        supplies = profile == "supplies" or is_supplies_collection(collection_id)
        if supplies:
            due_date = ""
            due_time = ""
            priority = ""
        else:
            normalized_due = validate_edit_due(due_date, due_time)
            if normalized_due is None:
                return web.json_response({"error": "task_edit_invalid_due"}, status=400)
            due_date, due_time = normalized_due
            if priority not in TASK_PRIORITIES:
                return web.json_response({"error": "task_edit_invalid_priority"}, status=400)
        old_title = str(task.get("summary") or "Untitled task")
        old_memo = str(task.get("description") or "")
        old_due = str(task.get("due") or "")
        old_due_time = str(task.get("dueTime") or "")
        old_priority = str(task.get("priority") or "")
        payload = {
            "uid": uid,
            "collectionId": collection_id,
            "title": new_title,
            "memo": new_memo,
            "dueDate": due_date,
            "dueTime": due_time,
            "priority": priority,
            "status": str(task.get("status") or "NEEDS-ACTION"),
        }
        payload = normalize_supplies_due(payload, collection_id=collection_id or profile)
        due_date = str(payload.get("dueDate") or "")
        due_time = str(payload.get("dueTime") or "")
        priority = str(payload.get("priority") or "")
        try:
            actor = Actor("user", actor_id, "family" if profile == "family" else "personal")
            operation, _created = self._durable.start_operation(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="calendar.tasks",
                    operation_type="edit",
                    parameters={
                        "profile": profile,
                        "uid": uid,
                        "collectionId": collection_id,
                        "oldTitle": old_title,
                        "newTitle": new_title,
                        "oldDue": old_due,
                        "oldDueTime": old_due_time,
                        "newDue": due_date,
                        "newDueTime": due_time,
                    },
                    requires_confirmation=True,
                )
            )
            confirmation = self._durable.create_confirmation(operation.operation_id, ttl=timedelta(minutes=10))
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        pending = PendingTaskEdit(
            profile=profile,
            uid=uid,
            collection_id=collection_id,
            old_title=old_title,
            new_title=new_title,
            old_memo=old_memo,
            new_memo=new_memo,
            old_due=old_due,
            old_due_time=old_due_time,
            new_due=due_date,
            new_due_time=due_time,
            old_priority=old_priority,
            new_priority=priority,
            payload=payload,
        )
        self._pending_task_edits[operation.operation_id] = pending
        return web.json_response(
            {
                "operationId": operation.operation_id,
                "confirmationId": confirmation.confirmation_id,
                "expiresAt": confirmation.expires_at.isoformat(),
                "task": _pending_task_edit_payload(pending),
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
        pending_task_edit = self._pending_task_edits.get(operation.operation_id)
        pending_event_create = self._pending_event_creates.get(operation.operation_id)
        pending_memo_create = self._pending_memo_creates.get(operation.operation_id)
        pending_memo_delete = self._pending_memo_deletes.get(operation.operation_id)
        pending_memo_edit = self._pending_memo_edits.get(operation.operation_id)
        pending_document_metadata = self._pending_document_metadata.get(operation.operation_id)
        if (
            pending_update is None
            and pending_create is None
            and pending_action is None
            and pending_task_edit is None
            and pending_event_create is None
            and pending_memo_create is None
            and pending_memo_delete is None
            and pending_memo_edit is None
            and pending_document_metadata is None
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
            elif pending_task_edit is not None:
                result = await asyncio.to_thread(
                    self._calendar_adapter.update_task,
                    pending_task_edit.profile,
                    pending_task_edit.payload,
                )
                task = _pending_task_edit_payload(pending_task_edit)
                result_uid = str(result.get("uid") or pending_task_edit.uid)
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
            elif pending_document_metadata is not None:
                document = await asyncio.to_thread(
                    self._paperless.update_metadata,
                    pending_document_metadata.document_id,
                    title=pending_document_metadata.title,
                    tags=pending_document_metadata.tags,
                )
                result_uid = str(document.document_id)
                document_payload = _completed_document_metadata_payload(pending_document_metadata, document.as_dict())
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
            if (
                pending_memo_create is None
                and pending_memo_delete is None
                and pending_memo_edit is None
                and pending_document_metadata is None
            ):
                await self._refresh_calendar_surfaces()
        except DurableGovernorError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except CalendarAdapterError as exc:
            self._durable.fail_operation(operation.operation_id, error_code="calendar_adapter_error")
            return web.json_response({"error": str(exc)}, status=502)
        except (ValueError, MemosError) as exc:
            self._durable.fail_operation(operation.operation_id, error_code=str(exc))
            return _memos_error(exc)
        except DocumentIntakeError as exc:
            self._durable.fail_operation(operation.operation_id, error_code=exc.code)
            return _document_error(exc)
        self._pending_task_due_updates.pop(operation.operation_id, None)
        self._pending_task_creates.pop(operation.operation_id, None)
        self._pending_task_actions.pop(operation.operation_id, None)
        self._pending_task_edits.pop(operation.operation_id, None)
        self._pending_event_creates.pop(operation.operation_id, None)
        self._pending_memo_creates.pop(operation.operation_id, None)
        self._pending_memo_deletes.pop(operation.operation_id, None)
        self._pending_memo_edits.pop(operation.operation_id, None)
        self._pending_document_metadata.pop(operation.operation_id, None)
        response_payload = {
            "operationId": operation.operation_id,
            "confirmationId": confirmation_id,
            "status": "completed",
            "source": _completed_operation_source(
                memo=pending_memo_create is not None or pending_memo_delete is not None or pending_memo_edit is not None,
                document=pending_document_metadata is not None,
            ),
        }
        if pending_memo_create is not None or pending_memo_delete is not None or pending_memo_edit is not None:
            response_payload["memo"] = memo_payload
        elif pending_document_metadata is not None:
            response_payload["document"] = document_payload
        elif pending_event_create is not None:
            response_payload["event"] = event
        else:
            response_payload["task"] = task
        return web.json_response(
            response_payload
        )

    async def _refresh_calendar_surfaces(self) -> None:
        if self._calendar_refresh_callback is None:
            return
        try:
            await self._calendar_refresh_callback()
        except Exception:
            LOGGER.exception("Brain tool calendar surface refresh failed")

    def _with_weather(self, profile: str, bootstrap: Mapping[str, Any], days: list[date], *, city: str = "") -> dict[str, Any]:
        payload = dict(bootstrap)
        try:
            kwargs = {"profile": profile, "start": min(days).isoformat(), "end": max(days).isoformat()}
            if city:
                kwargs["city"] = city
            weather = self._calendar_adapter.month_weather(
                **kwargs,
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


def upcoming_event_payloads(
    bootstrap: Mapping[str, Any],
    *,
    profile: str,
    current: date,
    days: int,
) -> list[dict[str, object]]:
    collections = collections_by_id(bootstrap)
    end = current + timedelta(days=days - 1)
    upcoming = [
        event_payload(item, collections)
        for item in items(bootstrap, "events")
        if _within_optional_range(item_date(item, "startDate"), current, end)
    ]
    return sorted(
        upcoming,
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("time") or ""),
            str(item.get("title") or ""),
            str(item.get("uid") or ""),
        ),
    )


def calendar_week_payload(bootstrap: Mapping[str, Any], *, profile: str, current: date, days: int) -> dict[str, object]:
    day_values = [current + timedelta(days=offset) for offset in range(days)]
    return {
        "date": current.isoformat(),
        "profile": profile,
        "days": days,
        "items": [today_payload(bootstrap, profile=profile, current=value) for value in day_values],
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
        "memo": str(item.get("description") or ""),
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
    payload = {
        "date": str(weather.get("date") or ""),
        "summary": weather_agenda_summary(weather),
        "condition": str(weather.get("condition") or weather.get("summary") or weather.get("weather") or ""),
        "minTemp": weather.get("minTemp", ""),
        "maxTemp": weather.get("maxTemp", ""),
    }
    for key in ("precipitationProbability", "precipitationMm", "humidityPercent", "windSpeedKmh"):
        if weather.get(key) not in (None, ""):
            payload[key] = weather.get(key)
    dayparts = weather.get("dayparts")
    if isinstance(dayparts, list):
        payload["dayparts"] = [dict(item) for item in dayparts if isinstance(item, Mapping)]
    return payload


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
        "memo": pending.memo,
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


def _pending_task_edit_payload(pending: PendingTaskEdit) -> dict[str, object]:
    return {
        "uid": pending.uid,
        "collectionId": pending.collection_id,
        "oldTitle": pending.old_title,
        "title": pending.new_title,
        "oldMemo": pending.old_memo,
        "memo": pending.new_memo,
        "oldDue": pending.old_due,
        "oldDueTime": pending.old_due_time,
        "due": pending.new_due,
        "dueTime": pending.new_due_time,
        "oldPriority": pending.old_priority,
        "priority": pending.new_priority,
        "action": "edit",
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


def _pending_document_metadata_payload(pending: PendingDocumentMetadata) -> dict[str, object]:
    return {
        "id": pending.document_id,
        "oldTitle": pending.old_title,
        "title": pending.title,
        "tags": list(pending.tags),
        "action": "update_metadata",
    }


def _document_tag_context_document_payload(document: Mapping[str, object]) -> dict[str, object]:
    payload = dict(document)
    content = str(payload.pop("content", "") or "")
    payload["contentExcerpt"] = content[:4000]
    payload["contentLength"] = len(content)
    return payload


SECOND_LOOK_ALLOWED_SOURCES = {"kaospacs-aio", "kaosaio"}


def _validate_second_look_request(body: Mapping[str, Any]) -> str:
    if str(body.get("source") or "").strip() not in SECOND_LOOK_ALLOWED_SOURCES:
        return "imaging_second_look_invalid_source"
    for name in ("requestId", "modality", "aiDomain", "question"):
        if not str(body.get(name) or "").strip():
            return "imaging_second_look_missing_required_field"
    safety = body.get("safety")
    if not isinstance(safety, Mapping):
        return "imaging_second_look_missing_safety"
    required_safety = {
        "temporary": True,
        "storedInAioReports": False,
        "dicomMetadataSent": False,
        "orthancReadOnly": True,
        "dicomModified": False,
        "pacsFinalReport": False,
        "renderedPreview": True,
    }
    for name, expected in required_safety.items():
        if safety.get(name) is not expected:
            return "imaging_second_look_safety_rejected"
    images = body.get("images")
    if not isinstance(images, list) or not images:
        return "imaging_second_look_missing_image"
    if len(images) > 4:
        return "imaging_second_look_too_many_images"
    for image in images:
        if not isinstance(image, Mapping):
            return "imaging_second_look_invalid_image"
        if str(image.get("format") or "").strip().lower() not in {"png", "jpg", "jpeg"}:
            return "imaging_second_look_unsupported_image_format"
        content = str(image.get("contentBase64") or "").strip()
        if not content:
            return "imaging_second_look_missing_image"
        try:
            decoded = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            return "imaging_second_look_invalid_image_base64"
        if not decoded or len(decoded) > 8 * 1024 * 1024:
            return "imaging_second_look_image_size_rejected"
    return ""


def _second_look_job_id(request_id: str) -> str:
    return "imaging_" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:24]


def _second_look_now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _status_int(payload: Mapping[str, object], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _second_look_operation_parameters(body: Mapping[str, Any]) -> dict[str, Any]:
    images = [image for image in body.get("images", []) if isinstance(image, Mapping)]
    safety = body.get("safety") if isinstance(body.get("safety"), Mapping) else {}
    return {
        "source": str(body.get("source") or "").strip(),
        "requestId": str(body.get("requestId") or "").strip(),
        "studyInstanceUidHash": _second_look_optional_hash(body.get("studyInstanceUid")),
        "seriesInstanceUidHash": _second_look_optional_hash(body.get("seriesInstanceUid")),
        "sopInstanceUidHash": _second_look_optional_hash(body.get("sopInstanceUid")),
        "modality": str(body.get("modality") or "").strip().upper(),
        "bodyPart": str(body.get("bodyPart") or "").strip().upper(),
        "viewPosition": str(body.get("viewPosition") or "").strip().upper(),
        "aiDomain": str(body.get("aiDomain") or "").strip().lower(),
        "questionHash": _second_look_optional_hash(body.get("question")),
        "imageCount": len(images),
        "imageFormats": [str(image.get("format") or "").strip().lower() for image in images],
        "imageHashes": [_second_look_image_hash(image) for image in images],
        "safety": {
            name: bool(safety.get(name))
            for name in (
                "temporary",
                "storedInAioReports",
                "dicomMetadataSent",
                "orthancReadOnly",
                "dicomModified",
                "pacsFinalReport",
                "renderedPreview",
                "burnedInAnnotationsPossible",
            )
        },
    }


def _second_look_optional_hash(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _second_look_image_hash(image: Mapping[str, Any]) -> str:
    content = str(image.get("contentBase64") or "").strip()
    try:
        decoded = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        return ""
    return hashlib.sha256(decoded).hexdigest()


def _second_look_result_audit_payload(response_payload: Mapping[str, Any]) -> dict[str, Any]:
    result = response_payload.get("result")
    if not isinstance(result, Mapping):
        return {"status": str(response_payload.get("status") or "").strip()}
    return {
        "status": str(response_payload.get("status") or "").strip(),
        "model": str(result.get("model") or "").strip(),
        "checklistCount": len(result.get("checklist", [])) if isinstance(result.get("checklist"), list) else 0,
        "cautionCount": len(result.get("cautions", [])) if isinstance(result.get("cautions"), list) else 0,
        "hasRecommendation": bool(str(result.get("recommendation") or "").strip()),
    }


def _second_look_error_code(value: str) -> str:
    text = "".join(character if character.isalnum() or character in "._:@/-" else "_" for character in value.strip())
    text = text.strip("._:@/-")
    if not text:
        return "imaging_second_look_failed"
    if not text[0].isalnum():
        text = f"imaging_{text}"
    return text[:128]


def _normalize_second_look_provider_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "completed").strip() or "completed"
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise RuntimeError("imaging_second_look_missing_result")
    normalized = {
        "status": status,
        "result": {
            "summary": str(result.get("summary") or "").strip(),
            "checklist": _string_items(result.get("checklist"), limit=10),
            "cautions": _string_items(result.get("cautions"), limit=8),
            "recommendation": str(result.get("recommendation") or "").strip(),
            "disclaimer": str(result.get("disclaimer") or "AI 보조 검토입니다. 최종 판단은 진료자가 합니다.").strip(),
            "model": str(result.get("model") or "unknown").strip(),
        },
    }
    fallback = result.get("fallback")
    if isinstance(fallback, Mapping):
        normalized["result"]["fallback"] = {
            "from": str(fallback.get("from") or "").strip(),
            "to": str(fallback.get("to") or "").strip(),
        }
    return normalized


def _string_items(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text[:800])
        if len(items) >= limit:
            break
    return items


def _completed_document_metadata_payload(
    pending: PendingDocumentMetadata,
    document: Mapping[str, object],
) -> dict[str, object]:
    return {
        **_pending_document_metadata_payload(pending),
        "document": dict(document),
    }


def _completed_operation_source(*, memo: bool, document: bool) -> str:
    if memo:
        return "memos-live"
    if document:
        return "paperless-live"
    return "calendar-adapter-live"


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


def _optional_int_query(request: web.Request, name: str, default: int) -> int:
    raw = request.query.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=f'{{"error": "invalid_{name}"}}', content_type="application/json") from exc


def _recent_import_payloads(status: Mapping[str, object]) -> list[dict[str, object]]:
    imports: list[dict[str, object]] = []
    mail = _mapping_value(status, "naverMail")
    organizer = _mapping_value(status, "naverMailOrganizer")
    fax = _mapping_value(status, "fax")
    documents = _mapping_value(status, "documentInbox")
    archived = _int_value(mail, "archivedCount")
    if archived:
        imports.append(
            {
                "kind": "mail",
                "title": f"Naver mail archived: {archived}",
                "detail": _status_detail(mail, "lastArchiveAt", "lastScanAt"),
            }
        )
    digest_count = _int_value(organizer, "digestCount")
    if digest_count:
        imports.append(
            {
                "kind": "mail",
                "title": f"Naver organizer digests: {digest_count}",
                "detail": _status_detail(organizer, "lastDigestAt", "lastCheckAt"),
            }
        )
    tracked_jobs = _int_value(fax, "trackedJobs")
    if tracked_jobs:
        imports.append(
            {
                "kind": "fax",
                "title": f"Fax jobs tracked: {tracked_jobs}",
                "detail": _status_detail(fax, "lastScanAt"),
            }
        )
    accepted_documents = _int_value(documents, "acceptedCount")
    ocr_ready = _int_value(documents, "ocrReadyCount")
    if accepted_documents or ocr_ready:
        imports.append(
            {
                "kind": "documents",
                "title": f"Documents accepted: {accepted_documents}",
                "detail": f"OCR ready: {ocr_ready}",
            }
        )
    return imports[:25]


def _normalize_recent_import_item(item: Mapping[str, object]) -> dict[str, object]:
    kind = str(item.get("kind") or "").strip().lower()
    if kind not in {"fax", "mail", "documents"}:
        kind = "import"
    direction = str(item.get("direction") or "").strip().lower()
    title = str(item.get("title") or "Import").strip() or "Import"
    detail = str(item.get("detail") or "").strip()
    payload: dict[str, object] = {
        "kind": kind,
        "title": title[:120],
    }
    if direction in {"incoming", "outgoing"}:
        payload["direction"] = direction
    if detail:
        payload["detail"] = detail[:180]
    for key in (
        "digestId",
        "itemId",
        "jobId",
        "faxId",
        "status",
        "destination",
        "remote",
        "pages",
        "createdAt",
        "completedAt",
        "receivedAt",
        "archivedAt",
    ):
        value = str(item.get(key) or "").strip()
        if value:
            payload[key] = value[:120]
    return payload


def _normalize_mail_list_item(item: Mapping[str, object]) -> dict[str, object]:
    subject = str(item.get("subject") or item.get("title") or "(No subject)").strip() or "(No subject)"
    sender = str(item.get("sender") or "").strip()
    mailbox = str(item.get("mailbox") or item.get("folder") or "").strip()
    received_at = str(item.get("receivedAt") or item.get("received_at") or "").strip()
    detail = " · ".join(part for part in (received_at[:16], sender, mailbox) if part)
    return {
        "kind": "mail",
        "direction": "incoming",
        "title": subject[:120],
        "subject": subject[:120],
        "sender": sender[:120],
        "mailbox": mailbox[:120],
        "receivedAt": received_at[:120],
        "preview": str(item.get("preview") or "").strip()[:1000],
        "attachmentCount": _safe_int(item.get("attachmentCount")),
        "uid": _safe_int(item.get("uid")),
        "detail": detail[:180],
    }


def _merge_recent_import_payloads(
    detailed: list[dict[str, object]],
    summary: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not detailed:
        return summary[:25]
    kinds = {str(item.get("kind") or "").strip().lower() for item in detailed}
    merged = list(detailed)
    for item in summary:
        kind = str(item.get("kind") or "").strip().lower()
        if kind == "documents" or kind not in kinds:
            merged.append(item)
    return merged[:50]


def _mapping_value(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _int_value(payload: Mapping[str, object], key: str) -> int:
    try:
        return max(0, int(payload.get(key, 0)))
    except (TypeError, ValueError):
        return 0


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _status_detail(payload: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    error = str(payload.get("lastError") or "").strip()
    return f"error: {error}" if error else "No recent timestamp"


def _normalized_tags(values: object) -> tuple[str, ...]:
    if not isinstance(values, list | tuple):
        return ()
    tags: list[str] = []
    for value in values:
        tag = " ".join(str(value or "").strip().lstrip("#").split())
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags[:25])


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
