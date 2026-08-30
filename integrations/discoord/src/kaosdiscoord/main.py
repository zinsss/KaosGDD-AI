import asyncio
import logging
import os
from pathlib import Path

from kaos_governor.database import wait_for_database_and_migrate
from kaos_governor.memos import MemosConfigurationError

from .bot import GovernorBot
from .config import ConfigurationError, Settings


MIGRATIONS = Path(
    os.environ.get("GOVERNOR_MIGRATIONS_DIR", "/usr/local/share/kaos-governor/migrations")
)


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if settings.operation_store == "postgres":
        try:
            wait_for_database_and_migrate(MIGRATIONS)
        except RuntimeError as exc:
            raise SystemExit("Governor operation database did not become ready") from exc

    try:
        bot = GovernorBot(settings)
    except MemosConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    async def run() -> None:
        async with bot:
            await bot.start(settings.token)

    asyncio.run(run())
