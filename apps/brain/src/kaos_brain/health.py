from __future__ import annotations

from dataclasses import dataclass
import hmac
import logging
from typing import Any

from aiohttp import web

from .calendar_preview import BrainCalendarPreviewServer
from .config import Settings
from .document_tags import BrainDocumentTagServer
from .imaging import BrainImagingServer
from .official_memos import BrainOfficialMemoServer
from .reauth import (
    OpenClawReauthClient,
    ReauthConfig,
    ReauthError,
    normalize_reauth_payload,
)
from .web_tasks import BrainOfficialWebTaskServer, BrainWebTaskServer


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrainHealthSnapshot:
    status: str
    runtime: str
    http_ready: bool
    chat_model: str
    deep_model: str
    imaging_provider: str
    imaging_model: str
    kaosai_mode: str
    governor_tools_enabled: bool

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "service": "kaos-brain",
            "runtime": self.runtime,
            "httpReady": self.http_ready,
            "chatModel": self.chat_model,
            "deepModel": self.deep_model,
            "imagingProvider": self.imaging_provider,
            "imagingModel": self.imaging_model,
            "kaosBrainOpenAI": {"mode": self.kaosai_mode},
            "kaosAI": {"mode": self.kaosai_mode},
            "governorTools": {"enabled": self.governor_tools_enabled},
        }


class BrainHealthServer:
    def __init__(
        self,
        settings: Settings,
        *,
        reauth_client: OpenClawReauthClient | None = None,
    ) -> None:
        self.settings = settings
        self.reauth = reauth_client or (
            OpenClawReauthClient(
                ReauthConfig(
                    base_url=settings.kaosai_reauth_base_url,
                    api_token=settings.kaosai_reauth_api_token,
                    timeout_seconds=settings.kaosai_reauth_timeout_seconds,
                )
            )
            if settings.kaosai_reauth_enabled
            else None
        )
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def application(self) -> web.Application:
        app = web.Application(client_max_size=32 * 1024 * 1024)
        app.router.add_get("/health", self.handle_health)
        app.router.add_post("/internal/openclaw-auth/start", self.handle_reauth_start)
        app.router.add_get("/internal/openclaw-auth/status", self.handle_reauth_status)
        app.router.add_post("/internal/calendar/smart-events/preview", BrainCalendarPreviewServer(self.settings).preview)
        app.router.add_post("/internal/documents/tag-suggestions/preview", BrainDocumentTagServer(self.settings).suggest)
        app.router.add_post("/internal/ai-tasks/official-doc-memo/preview", BrainOfficialMemoServer(self.settings).preview)
        app.router.add_post("/internal/ai-tasks/web/preview", BrainWebTaskServer(self.settings).preview)
        official_web = BrainOfficialWebTaskServer(self.settings)
        app.router.add_post("/internal/ai-tasks/official-web/plan", official_web.plan)
        app.router.add_post("/internal/ai-tasks/official-web/summarize", official_web.summarize)
        app.router.add_post("/imaging/second-look", BrainImagingServer(self.settings).second_look)
        return app

    async def start(self) -> None:
        app = self.application()
        runner = web.AppRunner(app)
        await runner.setup()
        self._runner = runner
        self._site = web.TCPSite(runner, self.settings.health_host, self.settings.health_port)
        await self._site.start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(snapshot(self.settings).payload())

    def _reauth_authorized(self, request: web.Request) -> bool:
        token = self.settings.ai_task_api_token
        if not token:
            return False
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    async def _reauth_payload(self, request: web.Request, *, start: bool) -> web.Response:
        if not self._reauth_authorized(request):
            return web.json_response(
                {"ok": False, "error": "kaosbrain_ai_task_unauthorized"},
                status=401,
            )
        if self.reauth is None:
            return web.json_response(
                {"ok": False, "error": "openclaw_reauth_not_configured"},
                status=503,
            )
        try:
            payload = normalize_reauth_payload(
                await (self.reauth.start() if start else self.reauth.status())
            )
        except ReauthError as exc:
            LOGGER.warning(
                "OpenClaw reauth agent %s failed (%s)",
                "start" if start else "status",
                type(exc).__name__,
            )
            return web.json_response(
                {"ok": False, "error": "openclaw_reauth_unavailable"},
                status=502,
            )
        return web.json_response({"ok": True, **payload})

    async def handle_reauth_start(self, request: web.Request) -> web.Response:
        return await self._reauth_payload(request, start=True)

    async def handle_reauth_status(self, request: web.Request) -> web.Response:
        return await self._reauth_payload(request, start=False)


def snapshot(settings: Settings) -> BrainHealthSnapshot:
    return BrainHealthSnapshot(
        status="ok",
        runtime="headless",
        http_ready=True,
        chat_model=settings.chat_model,
        deep_model=settings.deep_model,
        imaging_provider=settings.imaging_provider,
        imaging_model=settings.imaging_model,
        kaosai_mode=_kaosai_mode(settings),
        governor_tools_enabled=settings.governor_tools_enabled,
    )


def _kaosai_mode(settings: Settings) -> str:
    if not settings.kaosai_enabled:
        return "disabled"
    return "enabled"
