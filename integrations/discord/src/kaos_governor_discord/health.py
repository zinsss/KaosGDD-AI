from collections.abc import Callable
from aiohttp import web


class HealthServer:
    def __init__(self, host: str, port: int, status_provider: Callable[[], dict[str, object]]) -> None:
        self._host = host
        self._port = port
        self._status_provider = status_provider
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self._health)
        app.router.add_get("/ready", self._ready)
        self._runner = web.AppRunner(app, access_log=None)
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
        ready = bool(status["discordReady"])
        return web.json_response({"status": "ready" if ready else "not-ready", **status}, status=200 if ready else 503)
