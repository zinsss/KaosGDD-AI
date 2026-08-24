from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when runtime configuration is invalid."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return parsed


def _optional_positive_int(value: str, name: str) -> int:
    if not str(value or "").strip():
        return 0
    return _positive_int(value, name)


def _id_set(env: Mapping[str, str], name: str) -> frozenset[int]:
    values = frozenset(
        _positive_int(part.strip(), name)
        for part in _required(env, name).split(",")
        if part.strip()
    )
    if not values:
        raise ConfigurationError(f"{name} must contain at least one ID")
    return values


def _boolean(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _secret(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise ConfigurationError(f"set either {name} or {name}_FILE, not both")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigurationError(f"unable to read {name}_FILE") from exc


def _internal_http_url(value: str, name: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ConfigurationError(f"{name} must be an internal http URL")
    if parsed.username or parsed.password:
        raise ConfigurationError(f"{name} must not include credentials")
    if parsed.query or parsed.fragment:
        raise ConfigurationError(f"{name} must not include query or fragment")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "kaosgdd.net" or hostname.endswith(".kaosgdd.net"):
        raise ConfigurationError(f"{name} must not point at a public KaosGDD route")
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int
    allowed_user_ids: frozenset[int]
    allowed_channel_ids: frozenset[int]
    system_channel_id: int | None
    mail_archive_channel_id: int | None
    mail_organizer_channel_id: int | None
    fax_archive_channel_id: int | None
    fax_notification_channel_id: int | None
    fax_message_intake: bool
    calendar_enabled: bool
    calendar_channel_id: int | None
    calendar_profile: Literal["main", "family"]
    calendar_state_path: Path
    calendar_adapter_url: str
    tasks_enabled: bool
    tasks_channel_id: int | None
    tasks_profile: Literal["main", "family"]
    tasks_state_path: Path
    tasks_refresh_seconds: int
    task_due_notifications_enabled: bool
    task_due_notification_channel_id: int | None
    task_due_notification_state_path: Path
    supplies_enabled: bool
    supplies_channel_id: int | None
    supplies_profile: Literal["main", "family", "supplies"]
    supplies_state_path: Path
    supplies_collection_id: str
    memos_enabled: bool
    memos_channel_id: int | None
    inbox_enabled: bool
    inbox_channel_id: int | None
    inbox_extra_channel_ids: frozenset[int]
    inbox_state_path: Path
    service_status_enabled: bool
    service_status_channel_id: int | None
    service_status_state_path: Path
    startup_notification: bool
    health_host: str
    health_port: int
    brain_tools_enabled: bool
    brain_tools_host: str
    brain_tools_port: int
    governor_api_url: str
    governor_api_token: str
    paperless_api_token: str
    paperless_base_url: str
    paperless_public_url: str
    paperless_default_owner_id: int
    paperless_max_attachment_mb: int
    imaging_second_look_url: str
    imaging_second_look_token: str
    imaging_second_look_timeout_seconds: int
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        allowed_channels = _id_set(source, "DISCORD_ALLOWED_CHANNEL_IDS")
        raw_system = source.get("DISCORD_SYSTEM_CHANNEL_ID", "").strip()
        system_channel_id = _positive_int(raw_system, "DISCORD_SYSTEM_CHANNEL_ID") if raw_system else None
        if system_channel_id is not None and system_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_SYSTEM_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        legacy_mail = source.get("MAIL_DISCORD_CHANNEL_ID", "").strip()
        raw_archive = source.get("MAIL_ARCHIVE_DISCORD_CHANNEL_ID", "").strip() or legacy_mail
        raw_organizer = source.get("MAIL_ORGANIZER_DISCORD_CHANNEL_ID", "").strip() or legacy_mail
        mail_archive_channel_id = (
            _positive_int(raw_archive, "MAIL_ARCHIVE_DISCORD_CHANNEL_ID") if raw_archive else None
        )
        mail_organizer_channel_id = (
            _positive_int(raw_organizer, "MAIL_ORGANIZER_DISCORD_CHANNEL_ID") if raw_organizer else None
        )
        mail_enabled = _boolean(source, "MAIL_NAVER_ENABLED")
        organizer_enabled = _boolean(source, "MAIL_ORGANIZER_ENABLED")
        if (mail_enabled or organizer_enabled) and mail_archive_channel_id is None:
            raise ConfigurationError(
                "MAIL_ARCHIVE_DISCORD_CHANNEL_ID is required when Naver mail or its organizer is enabled"
            )
        if organizer_enabled and mail_organizer_channel_id is None:
            raise ConfigurationError(
                "MAIL_ORGANIZER_DISCORD_CHANNEL_ID is required when MAIL_ORGANIZER_ENABLED=true"
            )
        for name, channel_id in (
            ("MAIL_ARCHIVE_DISCORD_CHANNEL_ID", mail_archive_channel_id),
            ("MAIL_ORGANIZER_DISCORD_CHANNEL_ID", mail_organizer_channel_id),
        ):
            if channel_id is not None and channel_id not in allowed_channels:
                raise ConfigurationError(f"{name} must be in DISCORD_ALLOWED_CHANNEL_IDS")
        fax_enabled = _boolean(source, "FAX_DISCORD_ENABLED")
        fax_message_intake = _boolean(source, "FAX_DISCORD_MESSAGE_INTAKE")
        if fax_message_intake and not fax_enabled:
            raise ConfigurationError("FAX_DISCORD_ENABLED must be true when fax message intake is enabled")
        raw_fax_archive = source.get("FAX_ARCHIVE_DISCORD_CHANNEL_ID", "").strip()
        raw_fax_notification = source.get("FAX_NOTIFICATION_DISCORD_CHANNEL_ID", "").strip()
        fax_archive_channel_id = (
            _positive_int(raw_fax_archive, "FAX_ARCHIVE_DISCORD_CHANNEL_ID") if raw_fax_archive else None
        )
        fax_notification_channel_id = (
            _positive_int(raw_fax_notification, "FAX_NOTIFICATION_DISCORD_CHANNEL_ID")
            if raw_fax_notification
            else None
        )
        if fax_enabled and (fax_archive_channel_id is None or fax_notification_channel_id is None):
            raise ConfigurationError(
                "FAX_ARCHIVE_DISCORD_CHANNEL_ID and FAX_NOTIFICATION_DISCORD_CHANNEL_ID are required "
                "when FAX_DISCORD_ENABLED=true"
            )
        for name, channel_id in (
            ("FAX_ARCHIVE_DISCORD_CHANNEL_ID", fax_archive_channel_id),
            ("FAX_NOTIFICATION_DISCORD_CHANNEL_ID", fax_notification_channel_id),
        ):
            if channel_id is not None and channel_id not in allowed_channels:
                raise ConfigurationError(f"{name} must be in DISCORD_ALLOWED_CHANNEL_IDS")
        calendar_enabled = _boolean(source, "DISCORD_CALENDAR_ENABLED")
        raw_calendar_channel = source.get("DISCORD_CALENDAR_CHANNEL_ID", "").strip()
        calendar_channel_id = (
            _positive_int(raw_calendar_channel, "DISCORD_CALENDAR_CHANNEL_ID") if raw_calendar_channel else None
        )
        if calendar_enabled and calendar_channel_id is None:
            raise ConfigurationError("DISCORD_CALENDAR_CHANNEL_ID is required when DISCORD_CALENDAR_ENABLED=true")
        if calendar_channel_id is not None and calendar_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_CALENDAR_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        calendar_profile = source.get("DISCORD_CALENDAR_PROFILE", "main").strip().lower() or "main"
        if calendar_profile not in {"main", "family"}:
            raise ConfigurationError("DISCORD_CALENDAR_PROFILE must be main or family")
        calendar_state_path = Path(
            source.get("DISCORD_CALENDAR_STATE_PATH", "/data/discord-calendar/state.json").strip()
            or "/data/discord-calendar/state.json"
        )
        calendar_adapter_url = (
            source.get("CALENDAR_ADAPTER_INTERNAL_URL", "http://calendar-adapter:8091").strip()
            or "http://calendar-adapter:8091"
        )
        tasks_enabled = _boolean(source, "DISCORD_TASKS_ENABLED")
        raw_tasks_channel = source.get("DISCORD_TASKS_CHANNEL_ID", "").strip()
        tasks_channel_id = _positive_int(raw_tasks_channel, "DISCORD_TASKS_CHANNEL_ID") if raw_tasks_channel else None
        if tasks_enabled and tasks_channel_id is None:
            raise ConfigurationError("DISCORD_TASKS_CHANNEL_ID is required when DISCORD_TASKS_ENABLED=true")
        if tasks_channel_id is not None and tasks_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_TASKS_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        tasks_profile = source.get("DISCORD_TASKS_PROFILE", "main").strip().lower() or "main"
        if tasks_profile not in {"main", "family"}:
            raise ConfigurationError("DISCORD_TASKS_PROFILE must be main or family")
        tasks_state_path = Path(
            source.get("DISCORD_TASKS_STATE_PATH", "/data/discord-tasks/state.json").strip()
            or "/data/discord-tasks/state.json"
        )
        tasks_refresh_seconds = _positive_int(
            source.get("DISCORD_TASKS_REFRESH_SECONDS", "60"),
            "DISCORD_TASKS_REFRESH_SECONDS",
        )
        task_due_notifications_enabled = _boolean(source, "DISCORD_TASK_DUE_NOTIFICATIONS_ENABLED")
        raw_task_due_notification_channel = source.get("DISCORD_TASK_DUE_NOTIFICATION_CHANNEL_ID", "").strip()
        task_due_notification_channel_id = (
            _positive_int(raw_task_due_notification_channel, "DISCORD_TASK_DUE_NOTIFICATION_CHANNEL_ID")
            if raw_task_due_notification_channel
            else system_channel_id
        )
        if task_due_notifications_enabled and task_due_notification_channel_id is None:
            raise ConfigurationError(
                "DISCORD_TASK_DUE_NOTIFICATION_CHANNEL_ID or DISCORD_SYSTEM_CHANNEL_ID is required "
                "when DISCORD_TASK_DUE_NOTIFICATIONS_ENABLED=true"
            )
        if task_due_notification_channel_id is not None and task_due_notification_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_TASK_DUE_NOTIFICATION_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        task_due_notification_state_path = Path(
            source.get(
                "DISCORD_TASK_DUE_NOTIFICATION_STATE_PATH",
                "/data/discord-tasks/due-notifications.json",
            ).strip()
            or "/data/discord-tasks/due-notifications.json"
        )
        supplies_enabled = _boolean(source, "DISCORD_SUPPLIES_ENABLED")
        raw_supplies_channel = source.get("DISCORD_SUPPLIES_CHANNEL_ID", "").strip()
        supplies_channel_id = (
            _positive_int(raw_supplies_channel, "DISCORD_SUPPLIES_CHANNEL_ID") if raw_supplies_channel else None
        )
        if supplies_enabled and supplies_channel_id is None:
            raise ConfigurationError("DISCORD_SUPPLIES_CHANNEL_ID is required when DISCORD_SUPPLIES_ENABLED=true")
        if supplies_channel_id is not None and supplies_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_SUPPLIES_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        supplies_profile = source.get("DISCORD_SUPPLIES_PROFILE", "main").strip().lower() or "main"
        if supplies_profile not in {"main", "family", "supplies"}:
            raise ConfigurationError("DISCORD_SUPPLIES_PROFILE must be main, family, or supplies")
        supplies_state_path = Path(
            source.get("DISCORD_SUPPLIES_STATE_PATH", "/data/discord-supplies/state.json").strip()
            or "/data/discord-supplies/state.json"
        )
        supplies_collection_id = source.get("DISCORD_SUPPLIES_COLLECTION_ID", "").strip()
        memos_enabled = _boolean(source, "DISCORD_MEMOS_ENABLED")
        raw_memos_channel = source.get("DISCORD_MEMOS_CHANNEL_ID", "").strip()
        memos_channel_id = _positive_int(raw_memos_channel, "DISCORD_MEMOS_CHANNEL_ID") if raw_memos_channel else None
        if memos_enabled and memos_channel_id is None:
            raise ConfigurationError("DISCORD_MEMOS_CHANNEL_ID is required when DISCORD_MEMOS_ENABLED=true")
        if memos_channel_id is not None and memos_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_MEMOS_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        inbox_enabled = _boolean(source, "DISCORD_INBOX_ENABLED")
        raw_inbox_channel = source.get("DISCORD_INBOX_CHANNEL_ID", "").strip()
        inbox_channel_id = _positive_int(raw_inbox_channel, "DISCORD_INBOX_CHANNEL_ID") if raw_inbox_channel else None
        if inbox_enabled and inbox_channel_id is None:
            raise ConfigurationError("DISCORD_INBOX_CHANNEL_ID is required when DISCORD_INBOX_ENABLED=true")
        if inbox_channel_id is not None and inbox_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_INBOX_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        inbox_extra_channel_ids = {
            int(part.strip())
            for part in source.get("DISCORD_INBOX_EXTRA_CHANNEL_IDS", "").split(",")
            if part.strip()
        }
        if not inbox_extra_channel_ids.issubset(allowed_channels):
            raise ConfigurationError("DISCORD_INBOX_EXTRA_CHANNEL_IDS must be in DISCORD_ALLOWED_CHANNEL_IDS")
        inbox_state_path = Path(
            source.get("DISCORD_INBOX_STATE_PATH", "/data/discord-inbox/state.json").strip()
            or "/data/discord-inbox/state.json"
        )
        service_status_enabled = _boolean(source, "DISCORD_SERVICE_STATUS_ENABLED")
        raw_service_status_channel = source.get("DISCORD_SERVICE_STATUS_CHANNEL_ID", "").strip()
        service_status_channel_id = (
            _positive_int(raw_service_status_channel, "DISCORD_SERVICE_STATUS_CHANNEL_ID")
            if raw_service_status_channel
            else system_channel_id
        )
        if service_status_enabled and service_status_channel_id is None:
            raise ConfigurationError(
                "DISCORD_SERVICE_STATUS_CHANNEL_ID or DISCORD_SYSTEM_CHANNEL_ID is required "
                "when DISCORD_SERVICE_STATUS_ENABLED=true"
            )
        if service_status_channel_id is not None and service_status_channel_id not in allowed_channels:
            raise ConfigurationError("DISCORD_SERVICE_STATUS_CHANNEL_ID must be in DISCORD_ALLOWED_CHANNEL_IDS")
        service_status_state_path = Path(
            source.get("DISCORD_SERVICE_STATUS_STATE_PATH", "/data/discord-system/status.json").strip()
            or "/data/discord-system/status.json"
        )
        health_port = _positive_int(source.get("HEALTH_PORT", "8097"), "HEALTH_PORT")
        if health_port > 65535:
            raise ConfigurationError("HEALTH_PORT must be at most 65535")
        brain_tools_enabled = _boolean(source, "GOVERNOR_BRAIN_TOOLS_ENABLED")
        brain_tools_port = _positive_int(source.get("GOVERNOR_BRAIN_TOOLS_PORT", "8098"), "GOVERNOR_BRAIN_TOOLS_PORT")
        if brain_tools_port > 65535:
            raise ConfigurationError("GOVERNOR_BRAIN_TOOLS_PORT must be at most 65535")
        governor_api_url = source.get("GOVERNOR_API_INTERNAL_URL", "http://governor-api:8096").strip()
        if not governor_api_url:
            raise ConfigurationError("GOVERNOR_API_INTERNAL_URL is required")
        governor_api_token = _secret(source, "GOVERNOR_API_TOKEN")
        if (_boolean(source, "MEMOS_SEARCH_ENABLED") or brain_tools_enabled or tasks_enabled or supplies_enabled) and not governor_api_token:
            raise ConfigurationError(
                "GOVERNOR_API_TOKEN is required when Memos search, Brain tools, tasks, or supplies are enabled"
            )
        paperless_api_token = _secret(source, "PAPERLESS_API_TOKEN")
        paperless_base_url = (
            source.get("PAPERLESS_BASE_URL", "").strip()
            or source.get("PAPERLESS_INTERNAL_URL", "").strip()
        )
        if inbox_enabled and not paperless_base_url:
            raise ConfigurationError("PAPERLESS_BASE_URL is required when DISCORD_INBOX_ENABLED=true")
        if inbox_enabled and not paperless_api_token:
            raise ConfigurationError("PAPERLESS_API_TOKEN is required when DISCORD_INBOX_ENABLED=true")
        paperless_max_attachment_mb = _positive_int(
            source.get("PAPERLESS_INBOX_MAX_ATTACHMENT_MB", "20"),
            "PAPERLESS_INBOX_MAX_ATTACHMENT_MB",
        )
        imaging_second_look_url = source.get("IMAGING_SECOND_LOOK_URL", "").strip()
        imaging_second_look_token = _secret(source, "IMAGING_SECOND_LOOK_TOKEN") if imaging_second_look_url else ""
        if imaging_second_look_url:
            imaging_second_look_url = _internal_http_url(imaging_second_look_url, "IMAGING_SECOND_LOOK_URL")
            if not imaging_second_look_token:
                raise ConfigurationError(
                    "IMAGING_SECOND_LOOK_TOKEN or IMAGING_SECOND_LOOK_TOKEN_FILE is required when IMAGING_SECOND_LOOK_URL is set"
                )
        return cls(
            token=_secret(source, "DISCORD_BOT_TOKEN") or _required(source, "DISCORD_BOT_TOKEN"),
            guild_id=_positive_int(_required(source, "DISCORD_GUILD_ID"), "DISCORD_GUILD_ID"),
            allowed_user_ids=_id_set(source, "DISCORD_ALLOWED_USER_IDS"),
            allowed_channel_ids=allowed_channels,
            system_channel_id=system_channel_id,
            mail_archive_channel_id=mail_archive_channel_id,
            mail_organizer_channel_id=mail_organizer_channel_id,
            fax_archive_channel_id=fax_archive_channel_id,
            fax_notification_channel_id=fax_notification_channel_id,
            fax_message_intake=fax_message_intake,
            calendar_enabled=calendar_enabled,
            calendar_channel_id=calendar_channel_id,
            calendar_profile=calendar_profile,  # type: ignore[arg-type]
            calendar_state_path=calendar_state_path,
            calendar_adapter_url=calendar_adapter_url,
            tasks_enabled=tasks_enabled,
            tasks_channel_id=tasks_channel_id,
            tasks_profile=tasks_profile,  # type: ignore[arg-type]
            tasks_state_path=tasks_state_path,
            tasks_refresh_seconds=tasks_refresh_seconds,
            task_due_notifications_enabled=task_due_notifications_enabled,
            task_due_notification_channel_id=task_due_notification_channel_id,
            task_due_notification_state_path=task_due_notification_state_path,
            supplies_enabled=supplies_enabled,
            supplies_channel_id=supplies_channel_id,
            supplies_profile=supplies_profile,  # type: ignore[arg-type]
            supplies_state_path=supplies_state_path,
            supplies_collection_id=supplies_collection_id,
            memos_enabled=memos_enabled,
            memos_channel_id=memos_channel_id,
            inbox_enabled=inbox_enabled,
            inbox_channel_id=inbox_channel_id,
            inbox_extra_channel_ids=frozenset(inbox_extra_channel_ids),
            inbox_state_path=inbox_state_path,
            service_status_enabled=service_status_enabled,
            service_status_channel_id=service_status_channel_id,
            service_status_state_path=service_status_state_path,
            startup_notification=_boolean(source, "DISCORD_STARTUP_NOTIFICATION"),
            health_host=source.get("HEALTH_HOST", "0.0.0.0").strip() or "0.0.0.0",
            health_port=health_port,
            brain_tools_enabled=brain_tools_enabled,
            brain_tools_host=source.get("GOVERNOR_BRAIN_TOOLS_HOST", "0.0.0.0").strip() or "0.0.0.0",
            brain_tools_port=brain_tools_port,
            governor_api_url=governor_api_url,
            governor_api_token=governor_api_token,
            paperless_api_token=paperless_api_token,
            paperless_base_url=paperless_base_url,
            paperless_public_url=source.get("PAPERLESS_PUBLIC_URL", "").strip(),
            paperless_default_owner_id=_optional_positive_int(
                source.get("PAPERLESS_DEFAULT_OWNER_ID", ""),
                "PAPERLESS_DEFAULT_OWNER_ID",
            ),
            paperless_max_attachment_mb=paperless_max_attachment_mb,
            imaging_second_look_url=imaging_second_look_url,
            imaging_second_look_token=imaging_second_look_token,
            imaging_second_look_timeout_seconds=_positive_int(
                source.get("IMAGING_SECOND_LOOK_TIMEOUT_SECONDS", "180"),
                "IMAGING_SECOND_LOOK_TIMEOUT_SECONDS",
            ),
            log_level=source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
