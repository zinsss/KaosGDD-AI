from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


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
    startup_notification: bool
    health_host: str
    health_port: int
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
        health_port = _positive_int(source.get("HEALTH_PORT", "8097"), "HEALTH_PORT")
        if health_port > 65535:
            raise ConfigurationError("HEALTH_PORT must be at most 65535")
        return cls(
            token=_required(source, "DISCORD_BOT_TOKEN"),
            guild_id=_positive_int(_required(source, "DISCORD_GUILD_ID"), "DISCORD_GUILD_ID"),
            allowed_user_ids=_id_set(source, "DISCORD_ALLOWED_USER_IDS"),
            allowed_channel_ids=allowed_channels,
            system_channel_id=system_channel_id,
            mail_archive_channel_id=mail_archive_channel_id,
            mail_organizer_channel_id=mail_organizer_channel_id,
            fax_archive_channel_id=fax_archive_channel_id,
            fax_notification_channel_id=fax_notification_channel_id,
            fax_message_intake=fax_message_intake,
            startup_notification=_boolean(source, "DISCORD_STARTUP_NOTIFICATION"),
            health_host=source.get("HEALTH_HOST", "0.0.0.0").strip() or "0.0.0.0",
            health_port=health_port,
            log_level=source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
