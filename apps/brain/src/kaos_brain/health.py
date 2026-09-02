from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import web

from .config import Settings
from .imaging import BrainImagingServer


@dataclass(frozen=True)
class BrainHealthSnapshot:
    status: str
    discord_ready: bool
    chat_model: str
    deep_model: str
    imaging_provider: str
    imaging_model: str
    kaosai_mode: str
    governor_tools_enabled: bool

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "discordReady": self.discord_ready,
            "chatModel": self.chat_model,
            "deepModel": self.deep_model,
            "imagingProvider": self.imaging_provider,
            "imagingModel": self.imaging_model,
            "kaosBrainOpenAI": {"mode": self.kaosai_mode},
            "kaosAI": {"mode": self.kaosai_mode},
            "governorTools": {"enabled": self.governor_tools_enabled},
        }


class BrainHealthServer:
    def __init__(self, settings: Settings, bot: Any) -> None:
        self.settings = settings
        self.bot = bot
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        app = web.Application(client_max_size=32 * 1024 * 1024)
        app.router.add_get("/health", self.handle_health)
        app.router.add_post("/imaging/second-look", BrainImagingServer(self.settings).second_look)
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
        return web.json_response(snapshot(self.settings, self.bot).payload())


def snapshot(settings: Settings, bot: Any) -> BrainHealthSnapshot:
    discord_ready = bool(bot.is_ready()) if hasattr(bot, "is_ready") else False
    return BrainHealthSnapshot(
        status="ok",
        discord_ready=discord_ready,
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
    if settings.kaosai_dry_run_enabled:
        return "dry-run"
    if settings.kaosai_chat_enabled:
        return "chat"
    return "diagnostic"
