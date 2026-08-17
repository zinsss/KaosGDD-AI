from __future__ import annotations

import asyncio
import logging

from .bot import BrainBot
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
    bot = BrainBot(settings)

    async def run() -> None:
        health_server = BrainHealthServer(settings, bot) if settings.health_enabled else None
        async with bot:
            if health_server is not None:
                await health_server.start()
            try:
                await bot.start(settings.token)
            finally:
                if health_server is not None:
                    await health_server.stop()

    asyncio.run(run())
