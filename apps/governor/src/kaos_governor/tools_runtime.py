"""Standalone runtime for the transport-neutral Governor tool API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import signal
from typing import Mapping

from . import __version__
from .calendar import CalendarAdapterClient, CalendarAdapterConfig
from .database import wait_for_database_and_migrate
from .documents import PaperlessConfig, PaperlessDocumentService
from .fax import FaxConfig, FaxService
from .mail import MailOrganizerConfig, NaverMailConfig, NaverMailOrganizer, NaverMailPoller
from .memos import MemoMutationService, MemosConfig, MemosService
from .postgres_durable import PostgresDurableGovernorStore
from .tasks import TaskMutationService
from .tools import BrainToolServer, ImagingSecondLookClient, ImagingSecondLookConfig


LOGGER = logging.getLogger(__name__)


class ToolRuntimeConfigurationError(ValueError):
    pass


def _secret(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise ToolRuntimeConfigurationError(f"set either {name} or {name}_FILE, not both")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ToolRuntimeConfigurationError(f"unable to read {name}_FILE") from exc


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise ToolRuntimeConfigurationError(f"{name} must be an integer") from exc
    if value <= 0 or value > 65535:
        raise ToolRuntimeConfigurationError(f"{name} must be between 1 and 65535")
    return value


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


class GovernorToolsRuntime:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        source = os.environ if env is None else env
        self._host = source.get("GOVERNOR_TOOLS_HOST", "0.0.0.0").strip() or "0.0.0.0"
        self._port = _positive_int(source, "GOVERNOR_TOOLS_PORT", 8098)
        self._worker_status_path = Path(
            source.get("GOVERNOR_WORKER_STATE_PATH", "/data/notifications/governor-worker.json")
        )
        self._tool_status_path = Path(
            source.get("GOVERNOR_TOOLS_STATE_PATH", "/data/tools/second-look-status.json")
        )

        governor_token = _secret(source, "GOVERNOR_API_TOKEN")
        shortcuts_token = _secret(source, "IOS_SHORTCUTS_TOKEN")
        fax_shortcut_token = _secret(source, "IOS_FAX_SHORTCUT_TOKEN")
        if not governor_token:
            raise ToolRuntimeConfigurationError("GOVERNOR_API_TOKEN is required")
        if not shortcuts_token:
            raise ToolRuntimeConfigurationError("IOS_SHORTCUTS_TOKEN is required")
        if not fax_shortcut_token:
            raise ToolRuntimeConfigurationError("IOS_FAX_SHORTCUT_TOKEN is required")

        calendar_url = source.get(
            "CALENDAR_ADAPTER_INTERNAL_URL",
            "http://calendar-adapter:8091",
        ).strip()
        calendar = CalendarAdapterClient(CalendarAdapterConfig(calendar_url))
        memos = MemosService(MemosConfig.from_env(source))
        paperless = PaperlessDocumentService(PaperlessConfig.from_env(source))
        fax = FaxService(FaxConfig.from_env(source))
        mail_config = NaverMailConfig.from_env(source)
        mail = NaverMailPoller(mail_config)
        mail_organizer = NaverMailOrganizer(MailOrganizerConfig.from_env(source), mail_config)

        imaging_url = source.get("IMAGING_SECOND_LOOK_URL", "").strip()
        imaging_token = _secret(source, "IMAGING_SECOND_LOOK_TOKEN") if imaging_url else ""
        imaging_timeout = _positive_int(source, "IMAGING_SECOND_LOOK_TIMEOUT_SECONDS", 180)
        if imaging_url and not imaging_token:
            raise ToolRuntimeConfigurationError("IMAGING_SECOND_LOOK_TOKEN is required when imaging is enabled")

        self._memos = memos
        self._paperless = paperless
        self._fax = fax
        self._mail = mail
        self._mail_organizer = mail_organizer
        self.server = BrainToolServer(
            self._host,
            self._port,
            governor_api_token=governor_token,
            ios_shortcuts_token=shortcuts_token,
            ios_fax_shortcut_token=fax_shortcut_token,
            calendar_adapter=calendar,
            memos=memos,
            paperless=paperless,
            durable_store=PostgresDurableGovernorStore(),
            task_mutations=TaskMutationService(calendar),
            memo_mutations=MemoMutationService(memos),
            import_status_provider=self.import_status,
            system_status_provider=self.system_status,
            import_items_provider=lambda: fax.recent_items(limit=50),
            fax_document_provider=fax.incoming_document,
            fax_service=fax,
            fax_stage_root=Path(
                source.get("FAX_PROPOSAL_STAGE_ROOT", "/data/tools/fax-proposals")
            ),
            mail_messages_provider=lambda limit: mail.list_messages(limit=limit),
            imaging_second_look=ImagingSecondLookClient(
                ImagingSecondLookConfig(
                    url=imaging_url,
                    token=imaging_token,
                    timeout_seconds=imaging_timeout,
                )
            ),
            second_look_status_path=self._tool_status_path,
        )

    def _worker_status(self) -> dict[str, object]:
        return _read_json(self._worker_status_path)

    def import_status(self) -> dict[str, object]:
        worker = self._worker_status()
        return {
            "naverMail": worker.get("naverMail") or self._mail.status(),
            "naverMailOrganizer": self._mail_organizer.status(),
            "fax": worker.get("fax") or self._fax.status(),
            "documentInbox": {
                "enabled": self._paperless.config.enabled,
                "source": "paperless",
            },
        }

    def system_status(self) -> dict[str, object]:
        worker = self._worker_status()
        return {
            "version": __version__,
            "runtime": "governor-tools",
            "startupComplete": True,
            "brainTools": {
                "enabled": True,
                "host": self._host,
                "port": self._port,
            },
            "naverMail": worker.get("naverMail") or self._mail.status(),
            "naverMailOrganizer": self._mail_organizer.status(),
            "fax": worker.get("fax") or self._fax.status(),
            "textNotifications": worker.get("pushover") or {"enabled": False},
            "dailyDigest": worker.get("dailyDigest") or {"enabled": False},
            "worker": {"available": bool(worker), **worker},
            "memosSearch": self._memos.status(),
            "calendarSurface": {"enabled": False, "transport": "pwa"},
            "tasksSurface": {"enabled": False, "transport": "pwa"},
            "taskDueNotifications": {"enabled": False, "transport": "native"},
            "suppliesSurface": {"enabled": False, "transport": "pwa"},
            "memosCapture": {"enabled": False, "transport": "pwa"},
            "documentInbox": {"enabled": self._paperless.config.enabled, "transport": "pwa"},
            "serviceStatus": {"enabled": False, "transport": "pwa"},
        }


async def _run(runtime: GovernorToolsRuntime) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    await runtime.server.start()
    LOGGER.info("Governor tools listening on %s:%s", runtime._host, runtime._port)
    try:
        await stop.wait()
    finally:
        await runtime.server.stop()


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").strip().upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    wait_for_database_and_migrate(
        Path(os.environ.get("GOVERNOR_MIGRATIONS_DIR", "/usr/local/share/kaos-governor/migrations"))
    )
    try:
        runtime = GovernorToolsRuntime()
    except (ToolRuntimeConfigurationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    asyncio.run(_run(runtime))


if __name__ == "__main__":
    main()
