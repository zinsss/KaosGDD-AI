from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import date, timedelta
import hmac
import logging
from typing import Any

from aiohttp import web
from kaos_governor.calendar import CalendarAdapterClient, CalendarAdapterError, profile_host
from kaos_governor.documents import DocumentIntakeError, PaperlessDocumentService
from kaos_governor.memos import MemosError, MemosService

from .calendar import weather_agenda_summary, weather_items_by_date


LOGGER = logging.getLogger(__name__)


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
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._governor_api_token = governor_api_token
        self._calendar_adapter = calendar_adapter
        self._memos = memos
        self._paperless = paperless
        self._today_provider = today_provider or date.today
        self._runner: web.AppRunner | None = None

    def application(self) -> web.Application:
        app = web.Application(client_max_size=32 * 1024)
        app.middlewares.append(self._auth_middleware)
        app.router.add_get("/tools/today", self._today)
        app.router.add_get("/tools/tasks/active", self._active_tasks)
        app.router.add_get("/tools/memos/search", self._search_memos)
        app.router.add_get("/tools/memos/{memo_id}", self._get_memo)
        app.router.add_get("/tools/documents/search", self._search_documents)
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
    return {
        "uid": str(item.get("uid") or ""),
        "title": str(item.get("summary") or "Untitled task"),
        "due": str(item.get("due") or ""),
        "dueTime": str(item.get("dueTime") or ""),
        "status": str(item.get("status") or ""),
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
