from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


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


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int
    allowed_user_ids: frozenset[int]
    brain_channel_id: int
    ollama_base_url: str
    chat_model: str
    deep_model: str
    request_timeout_seconds: int
    max_reply_chars: int
    respond_without_mention: bool
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
        timeout = _positive_int(source.get("KAOSBRAIN_REQUEST_TIMEOUT_SECONDS", "90"), "KAOSBRAIN_REQUEST_TIMEOUT_SECONDS")
        max_reply_chars = _positive_int(source.get("KAOSBRAIN_MAX_REPLY_CHARS", "1800"), "KAOSBRAIN_MAX_REPLY_CHARS")
        if max_reply_chars > 1900:
            raise ConfigurationError("KAOSBRAIN_MAX_REPLY_CHARS must be at most 1900")
        return cls(
            token=token,
            guild_id=guild_id,
            allowed_user_ids=allowed_user_ids,
            brain_channel_id=brain_channel_id,
            ollama_base_url=source.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
            or "http://127.0.0.1:11434",
            chat_model=source.get("KAOSBRAIN_CHAT_MODEL", "gemma3:4b").strip() or "gemma3:4b",
            deep_model=source.get("KAOSBRAIN_DEEP_MODEL", "qwen3:8b").strip() or "qwen3:8b",
            request_timeout_seconds=timeout,
            max_reply_chars=max_reply_chars,
            respond_without_mention=_boolean(source, "KAOSBRAIN_RESPOND_WITHOUT_MENTION", default=True),
            log_level=source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
