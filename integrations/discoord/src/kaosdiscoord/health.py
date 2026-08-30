import asyncio
from collections.abc import Callable
import hmac
import logging

from aiohttp import web
from kaos_governor.memos import MemosError, MemosService
from kaos_governor.settings import GovernorSettingsError, MemoryGovernorSettingsStore


LOGGER = logging.getLogger(__name__)


class HealthServer:
    def __init__(
        self,
        host: str,
        port: int,
        status_provider: Callable[[], dict[str, object]],
        *,
        governor_api_token: str = "",
        memos: MemosService | None = None,
        settings_store: MemoryGovernorSettingsStore | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._status_provider = status_provider
        self._governor_api_token = governor_api_token
        self._memos = memos
        self._settings_store = settings_store or MemoryGovernorSettingsStore()
        self._runner: web.AppRunner | None = None

    def application(self) -> web.Application:
        app = web.Application(client_max_size=32 * 1024)
        app.router.add_get("/health", self._health)
        app.router.add_get("/ready", self._ready)
        app.router.add_post("/api/v1/memos/search", self._search_memos)
        app.router.add_get("/api/v1/memos/{memo_id}", self._get_memo)
        app.router.add_get("/api/v1/settings/calendar", self._get_calendar_settings)
        app.router.add_patch("/api/v1/settings/calendar", self._update_calendar_settings)
        return app

    async def start(self) -> None:
        self._runner = web.AppRunner(self.application(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self._host, self._port).start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", **self._status_provider()})

    async def _ready(self, request: web.Request) -> web.Response:
        status = self._status_provider()
        ready = bool(status["discordReady"]) and bool(status.get("startupComplete", True))
        return web.json_response({"status": "ready" if ready else "not-ready", **status}, status=200 if ready else 503)

    def _authorized(self, request: web.Request) -> bool:
        if not self._governor_api_token:
            return False
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {self._governor_api_token}"
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    def _require_tool_access(self, request: web.Request) -> web.Response | None:
        if not self._authorized(request):
            return web.json_response({"error": "governor_api_unauthorized"}, status=401)
        if self._memos is None or not self._memos.config.enabled:
            return web.json_response({"error": "memos_search_disabled"}, status=503)
        return None

    def _require_admin_access(self, request: web.Request) -> web.Response | None:
        if not self._authorized(request):
            return web.json_response({"error": "governor_api_unauthorized"}, status=401)
        return None

    async def _search_memos(self, request: web.Request) -> web.Response:
        denied = self._require_tool_access(request)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "invalid_request"}, status=400)
        try:
            results = await asyncio.to_thread(
                self._memos.search,
                payload.get("query", ""),
                payload.get("tags"),
                payload.get("limit"),
            )
        except (ValueError, MemosError) as exc:
            return self._tool_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Memos search failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response(
            {
                "query": " ".join(str(payload.get("query") or "").split()),
                "tags": payload.get("tags") or [],
                "count": len(results),
                "results": [result.as_dict() for result in results],
                "source": "memos-live",
            }
        )

    async def _get_memo(self, request: web.Request) -> web.Response:
        denied = self._require_tool_access(request)
        if denied is not None:
            return denied
        try:
            memo = await asyncio.to_thread(self._memos.get, f"memos/{request.match_info['memo_id']}")
        except (ValueError, MemosError) as exc:
            return self._tool_error(exc)
        except Exception:
            LOGGER.exception("Unexpected Memos fetch failure")
            return web.json_response({"error": "internal_error"}, status=500)
        return web.json_response({"memo": memo.as_dict(), "source": "memos-live"})

    async def _get_calendar_settings(self, request: web.Request) -> web.Response:
        denied = self._require_admin_access(request)
        if denied is not None:
            return denied
        return web.json_response(self._settings_store.get_calendar().as_dict())

    async def _update_calendar_settings(self, request: web.Request) -> web.Response:
        denied = self._require_admin_access(request)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "invalid_request"}, status=400)
        try:
            record = self._settings_store.update_calendar(payload)
        except GovernorSettingsError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(record.as_dict())

    @staticmethod
    def _tool_error(error: ValueError | MemosError) -> web.Response:
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
