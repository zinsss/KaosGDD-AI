from __future__ import annotations

import asyncio
import logging
import signal

from .config import ConfigurationError, Settings
from .health import BrainHealthServer


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    async def run() -> None:
        server = BrainHealthServer(settings)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        installed_signals: list[signal.Signals] = []
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signal_name, stop.set)
                installed_signals.append(signal_name)
            except NotImplementedError:  # pragma: no cover - non-POSIX fallback
                pass
        await server.start()
        logging.getLogger(__name__).info(
            "KaosBrain headless API listening on %s:%s",
            settings.health_host,
            settings.health_port,
        )
        try:
            await stop.wait()
        finally:
            for signal_name in installed_signals:
                loop.remove_signal_handler(signal_name)
            await server.stop()

    asyncio.run(run())
