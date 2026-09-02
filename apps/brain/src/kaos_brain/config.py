from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when KaosBrain runtime configuration is invalid."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


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


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ConfigurationError(f"{name} must be non-negative")
    return parsed


def _hour(value: str, name: str) -> int:
    parsed = _non_negative_int(value, name)
    if parsed > 23:
        raise ConfigurationError(f"{name} must be between 0 and 23")
    return parsed


def _optional_id(env: Mapping[str, str], name: str) -> int:
    value = env.get(name, "").strip()
    return _positive_int(value, name) if value else 0


def _id_set(env: Mapping[str, str], name: str) -> frozenset[int]:
    values = frozenset(
        _positive_int(part.strip(), name)
        for part in _required(env, name).split(",")
        if part.strip()
    )
    if not values:
        raise ConfigurationError(f"{name} must contain at least one ID")
    return values


def _boolean(env: Mapping[str, str], name: str, *, default: bool = False) -> bool:
    raw = env.get(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _internal_http_base_url(value: str, name: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ConfigurationError(f"{name} must be an internal http URL")
    if parsed.username or parsed.password:
        raise ConfigurationError(f"{name} must not include credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ConfigurationError(f"{name} must be a base URL without path, query, or fragment")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "kaosgdd.net" or hostname.endswith(".kaosgdd.net"):
        raise ConfigurationError(f"{name} must not point at a public KaosGDD route")
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int
    allowed_user_ids: frozenset[int]
    brain_channel_id: int
    notification_channel_id: int
    governor_bot_user_id: int
    ollama_base_url: str
    chat_model: str
    deep_model: str
    imaging_provider: str
    imaging_model: str
    request_timeout_seconds: int
    max_reply_chars: int
    respond_without_mention: bool
    auto_route_enabled: bool
    kaosai_enabled: bool
    kaosai_chat_enabled: bool
    kaosai_dry_run_enabled: bool
    kaosai_provider: str
    kaosai_base_url: str
    kaosai_model: str
    kaosai_api_token: str
    kaosai_timeout_seconds: int
    kaosai_reauth_enabled: bool
    kaosai_reauth_base_url: str
    kaosai_reauth_api_token: str
    kaosai_reauth_timeout_seconds: int
    governor_tools_enabled: bool
    governor_tools_base_url: str
    governor_tools_api_token: str
    governor_tools_profile: str
    governor_tools_supplies_collection_id: str
    active_control_state_path: str
    active_control_repost_seconds: int
    active_control_quiet_start_hour: int
    active_control_quiet_end_hour: int
    governor_tools_timeout_seconds: int
    imaging_enabled: bool
    imaging_api_token: str
    memos_public_url: str
    paperless_public_url: str
    health_enabled: bool
    health_host: str
    health_port: int
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        token = _secret(source, "DISCORD_BOT_TOKEN")
        if not token:
            raise ConfigurationError("DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN_FILE is required")
        guild_id = _positive_int(_required(source, "DISCORD_GUILD_ID"), "DISCORD_GUILD_ID")
        allowed_user_ids = _id_set(source, "DISCORD_ALLOWED_USER_IDS")
        brain_channel_id = _positive_int(_required(source, "DISCORD_BRAIN_CHANNEL_ID"), "DISCORD_BRAIN_CHANNEL_ID")
        notification_channel_id = _optional_id(source, "DISCORD_NOTIFICATION_CHANNEL_ID")
        governor_bot_user_id = _optional_id(source, "DISCORD_GOVERNOR_BOT_USER_ID")
        if bool(notification_channel_id) != bool(governor_bot_user_id):
            raise ConfigurationError(
                "DISCORD_NOTIFICATION_CHANNEL_ID and DISCORD_GOVERNOR_BOT_USER_ID must be configured together"
            )
        timeout = _positive_int(source.get("KAOSBRAIN_REQUEST_TIMEOUT_SECONDS", "90"), "KAOSBRAIN_REQUEST_TIMEOUT_SECONDS")
        governor_tools_api_token = _secret(source, "GOVERNOR_API_TOKEN")
        governor_tools_enabled = _boolean(source, "KAOSBRAIN_GOVERNOR_TOOLS_ENABLED")
        if governor_tools_enabled and not governor_tools_api_token:
            raise ConfigurationError(
                "GOVERNOR_API_TOKEN or GOVERNOR_API_TOKEN_FILE is required when KAOSBRAIN_GOVERNOR_TOOLS_ENABLED=true"
            )
        governor_tools_base_url = source.get("KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL", "").strip()
        if governor_tools_enabled and not governor_tools_base_url:
            raise ConfigurationError("KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL is required when Governor tools are enabled")
        if governor_tools_enabled:
            governor_tools_base_url = _internal_http_base_url(
                governor_tools_base_url,
                "KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL",
            )
        imaging_enabled = _boolean(source, "KAOSBRAIN_IMAGING_ENABLED")
        imaging_provider = source.get("KAOSBRAIN_IMAGING_PROVIDER", "ollama").strip().lower() or "ollama"
        if imaging_provider == "kaosbrain-openai":
            imaging_provider = "kaosai"
        if imaging_provider not in {"ollama", "kaosai"}:
            raise ConfigurationError("KAOSBRAIN_IMAGING_PROVIDER must be ollama or kaosbrain-openai")
        imaging_api_token = _secret(source, "KAOSBRAIN_IMAGING_API_TOKEN") if imaging_enabled else ""
        if imaging_enabled and not imaging_api_token:
            raise ConfigurationError(
                "KAOSBRAIN_IMAGING_API_TOKEN or KAOSBRAIN_IMAGING_API_TOKEN_FILE is required when KAOSBRAIN_IMAGING_ENABLED=true"
            )
        kaosai_enabled = _boolean(source, "KAOSAI_ENABLED")
        kaosai_provider = source.get("KAOSAI_PROVIDER", "disabled").strip().lower() or "disabled"
        if not kaosai_enabled:
            kaosai_provider = "disabled"
        if kaosai_enabled and kaosai_provider not in {"openclaw"}:
            raise ConfigurationError("KAOSAI_PROVIDER must be openclaw when KAOSAI_ENABLED=true")
        kaosai_base_url = source.get("KAOSAI_BASE_URL", "").strip()
        if kaosai_enabled and not kaosai_base_url:
            raise ConfigurationError("KAOSAI_BASE_URL is required when KAOSAI_ENABLED=true")
        kaosai_api_token = _secret(source, "KAOSAI_API_TOKEN") if kaosai_enabled else ""
        if kaosai_enabled and not kaosai_api_token:
            raise ConfigurationError("KAOSAI_API_TOKEN or KAOSAI_API_TOKEN_FILE is required when KAOSAI_ENABLED=true")
        kaosai_dry_run_enabled = _boolean(source, "KAOSAI_DRY_RUN_ENABLED")
        if kaosai_dry_run_enabled and not kaosai_enabled:
            raise ConfigurationError("KAOSAI_ENABLED=true is required when KAOSAI_DRY_RUN_ENABLED=true")
        kaosai_chat_enabled = _boolean(source, "KAOSAI_CHAT_ENABLED")
        if kaosai_chat_enabled and not kaosai_enabled:
            raise ConfigurationError("KAOSAI_ENABLED=true is required when KAOSAI_CHAT_ENABLED=true")
        if kaosai_chat_enabled and kaosai_dry_run_enabled:
            raise ConfigurationError("KAOSAI_CHAT_ENABLED and KAOSAI_DRY_RUN_ENABLED cannot both be true")
        if imaging_enabled and imaging_provider == "kaosai" and not kaosai_enabled:
            raise ConfigurationError(
                "KAOSAI_ENABLED=true is required when KAOSBRAIN_IMAGING_PROVIDER=kaosbrain-openai"
            )
        kaosai_reauth_enabled = _boolean(source, "KAOSAI_REAUTH_ENABLED")
        kaosai_reauth_base_url = source.get("KAOSAI_REAUTH_BASE_URL", "").strip()
        kaosai_reauth_api_token = _secret(source, "KAOSAI_REAUTH_TOKEN") if kaosai_reauth_enabled else ""
        if kaosai_reauth_enabled:
            if not kaosai_reauth_base_url:
                raise ConfigurationError("KAOSAI_REAUTH_BASE_URL is required when KAOSAI_REAUTH_ENABLED=true")
            kaosai_reauth_base_url = _internal_http_base_url(kaosai_reauth_base_url, "KAOSAI_REAUTH_BASE_URL")
            if not kaosai_reauth_api_token:
                raise ConfigurationError("KAOSAI_REAUTH_TOKEN or KAOSAI_REAUTH_TOKEN_FILE is required")
        max_reply_chars = _positive_int(source.get("KAOSBRAIN_MAX_REPLY_CHARS", "1800"), "KAOSBRAIN_MAX_REPLY_CHARS")
        if max_reply_chars > 1900:
            raise ConfigurationError("KAOSBRAIN_MAX_REPLY_CHARS must be at most 1900")
        return cls(
            token=token,
            guild_id=guild_id,
            allowed_user_ids=allowed_user_ids,
            brain_channel_id=brain_channel_id,
            notification_channel_id=notification_channel_id,
            governor_bot_user_id=governor_bot_user_id,
            ollama_base_url=source.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
            or "http://127.0.0.1:11434",
            chat_model=source.get("KAOSBRAIN_CHAT_MODEL", "gemma3:4b").strip() or "gemma3:4b",
            deep_model=source.get("KAOSBRAIN_DEEP_MODEL", "qwen3:8b").strip() or "qwen3:8b",
            imaging_provider=imaging_provider,
            imaging_model=source.get("KAOSBRAIN_IMAGING_MODEL", "gemma3:4b").strip() or "gemma3:4b",
            request_timeout_seconds=timeout,
            max_reply_chars=max_reply_chars,
            respond_without_mention=_boolean(source, "KAOSBRAIN_RESPOND_WITHOUT_MENTION", default=True),
            auto_route_enabled=_boolean(source, "KAOSBRAIN_AUTO_ROUTE_ENABLED", default=True),
            kaosai_enabled=kaosai_enabled,
            kaosai_chat_enabled=kaosai_chat_enabled,
            kaosai_dry_run_enabled=kaosai_dry_run_enabled,
            kaosai_provider=kaosai_provider,
            kaosai_base_url=kaosai_base_url,
            kaosai_model=source.get("KAOSAI_MODEL", "default").strip() or "default",
            kaosai_api_token=kaosai_api_token,
            kaosai_timeout_seconds=_positive_int(source.get("KAOSAI_TIMEOUT_SECONDS", "30"), "KAOSAI_TIMEOUT_SECONDS"),
            kaosai_reauth_enabled=kaosai_reauth_enabled,
            kaosai_reauth_base_url=kaosai_reauth_base_url,
            kaosai_reauth_api_token=kaosai_reauth_api_token,
            kaosai_reauth_timeout_seconds=_positive_int(
                source.get("KAOSAI_REAUTH_TIMEOUT_SECONDS", "60"),
                "KAOSAI_REAUTH_TIMEOUT_SECONDS",
            ),
            governor_tools_enabled=governor_tools_enabled,
            governor_tools_base_url=governor_tools_base_url,
            governor_tools_api_token=governor_tools_api_token,
            governor_tools_profile=source.get("KAOSBRAIN_GOVERNOR_TOOLS_PROFILE", "main").strip() or "main",
            governor_tools_supplies_collection_id=source.get("KAOSBRAIN_SUPPLIES_COLLECTION_ID", "").strip(),
            active_control_state_path=source.get(
                "KAOSBRAIN_ACTIVE_CONTROL_STATE_PATH",
                "/data/kaosbrain/active-control.json",
            ).strip()
            or "/data/kaosbrain/active-control.json",
            active_control_repost_seconds=_non_negative_int(
                source.get("KAOSBRAIN_ACTIVE_CONTROL_REPOST_SECONDS", "7200"),
                "KAOSBRAIN_ACTIVE_CONTROL_REPOST_SECONDS",
            ),
            active_control_quiet_start_hour=_hour(
                source.get("KAOSBRAIN_ACTIVE_CONTROL_QUIET_START_HOUR", "0"),
                "KAOSBRAIN_ACTIVE_CONTROL_QUIET_START_HOUR",
            ),
            active_control_quiet_end_hour=_hour(
                source.get("KAOSBRAIN_ACTIVE_CONTROL_QUIET_END_HOUR", "7"),
                "KAOSBRAIN_ACTIVE_CONTROL_QUIET_END_HOUR",
            ),
            governor_tools_timeout_seconds=_positive_int(
                source.get("KAOSBRAIN_GOVERNOR_TOOLS_TIMEOUT_SECONDS", "10"),
                "KAOSBRAIN_GOVERNOR_TOOLS_TIMEOUT_SECONDS",
            ),
            imaging_enabled=imaging_enabled,
            imaging_api_token=imaging_api_token,
            memos_public_url=source.get("KAOSBRAIN_MEMOS_PUBLIC_URL", "").strip().rstrip("/"),
            paperless_public_url=source.get("KAOSBRAIN_PAPERLESS_PUBLIC_URL", "").strip().rstrip("/"),
            health_enabled=_boolean(source, "KAOSBRAIN_HEALTH_ENABLED"),
            health_host=source.get("KAOSBRAIN_HEALTH_HOST", "127.0.0.1").strip() or "127.0.0.1",
            health_port=_positive_int(source.get("KAOSBRAIN_HEALTH_PORT", "8099"), "KAOSBRAIN_HEALTH_PORT"),
            log_level=source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
