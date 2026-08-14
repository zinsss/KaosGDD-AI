from __future__ import annotations

import asyncio
import logging

from .bot import BrainBot
from .config import ConfigurationError, Settings


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
        async with bot:
            await bot.start(settings.token)

    asyncio.run(run())
