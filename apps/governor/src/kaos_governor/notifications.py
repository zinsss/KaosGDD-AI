from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import threading
from typing import Iterator, Literal, Mapping
import urllib.parse
import urllib.request


MIRRORED_CATEGORIES = frozenset({"daily", "fax", "mail", "maintenance", "system"})


class NotificationError(ValueError):
    pass


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise NotificationError(f"{name} must be true or false")


def _int(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise NotificationError(f"{name} must be an integer") from exc
    return max(minimum, value)


def _bounded_int(
    env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise NotificationError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise NotificationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _secret(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise NotificationError(f"{name} ambiguous")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise NotificationError(f"{name}_FILE unreadable") from exc


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _plain_text(value: str) -> str:
    text = value.replace("\u200b", "")
    text = re.sub(r"<@!?[0-9]+>", "", text)
    text = re.sub(r"<@&[0-9]+>", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^-#\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("~~", "").replace("`", "")
    text = re.sub(r"\\([\\`*_[\]{}()#+.!|>-])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass(frozen=True)
class PushoverConfig:
    enabled: bool = False
    state_path: Path = Path("/data/notifications/pushover.json")
    app_token: str = ""
    user_key: str = ""
    priority: int = 0
    timeout_seconds: int = 10
    poll_seconds: int = 10
    delivery_mode: Literal["inline", "worker"] = "inline"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PushoverConfig":
        source = os.environ if env is None else env
        enabled = _bool(source, "PUSHOVER_ENABLED")
        app_token = _secret(source, "PUSHOVER_APP_TOKEN") if enabled else ""
        user_key = _secret(source, "PUSHOVER_USER_KEY") if enabled else ""
        if enabled and (not app_token or not user_key):
            raise NotificationError(
                "PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY are required when PUSHOVER_ENABLED=true"
            )
        delivery_mode = source.get("PUSHOVER_DELIVERY_MODE", "inline").strip().lower() or "inline"
        if delivery_mode not in {"inline", "worker"}:
            raise NotificationError("PUSHOVER_DELIVERY_MODE must be inline or worker")
        return cls(
            enabled=enabled,
            state_path=Path(
                source.get("PUSHOVER_STATE_PATH", "/data/notifications/pushover.json")
            ),
            app_token=app_token,
            user_key=user_key,
            priority=_bounded_int(source, "PUSHOVER_PRIORITY", 0, 0, 1),
            timeout_seconds=_int(source, "PUSHOVER_TIMEOUT_SECONDS", 10, 1),
            poll_seconds=_int(source, "PUSHOVER_POLL_SECONDS", 10, 5),
            delivery_mode=delivery_mode,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class TextNotification:
    key: str
    category: str
    title: str
    message: str
    priority: int | None = None


def _notification_priority(value: object, *, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        priority = int(value)
    except (TypeError, ValueError) as exc:
        raise NotificationError("notification_priority_invalid") from exc
    if priority not in {0, 1}:
        raise NotificationError("notification_priority_invalid")
    return priority


class PushoverClient:
    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, config: PushoverConfig, *, urlopen=None) -> None:
        self.config = config
        self._urlopen = urlopen or urllib.request.urlopen

    def send(self, notification: TextNotification) -> None:
        if not self.config.enabled:
            raise NotificationError("pushover_not_configured")
        values = {
            "token": self.config.app_token,
            "user": self.config.user_key,
            "message": notification.message[:1024],
            "priority": str(
                _notification_priority(
                    notification.priority,
                    fallback=self.config.priority,
                )
            ),
        }
        if notification.title:
            values["title"] = notification.title[:250]
        payload = urllib.parse.urlencode(values).encode("utf-8")
        request = urllib.request.Request(
            self.API_URL,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NotificationError("pushover_delivery_failed") from exc
        if not isinstance(result, dict) or result.get("status") != 1:
            raise NotificationError("pushover_rejected")


class TextNotificationService:
    def __init__(
        self,
        config: PushoverConfig,
        *,
        client: PushoverClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or PushoverClient(config)
        self._lock = threading.RLock()
        self._delivery_lock = threading.Lock()

    @contextmanager
    def _state_lock(self) -> Iterator[None]:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.config.state_path.with_name(f"{self.config.state_path.name}.lock")
        with self._lock, lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, object]:
        try:
            value = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        value["pending"] = value.get("pending") if isinstance(value.get("pending"), dict) else {}
        value["delivered"] = (
            value.get("delivered") if isinstance(value.get("delivered"), dict) else {}
        )
        return value

    def _save(self, state: dict[str, object]) -> None:
        state["version"] = 1
        _atomic_json(self.config.state_path, state)

    def enqueue(self, notification: TextNotification) -> bool:
        if not self.config.enabled:
            return False
        key = str(notification.key).strip()
        category = str(notification.category).strip().lower()
        title = _plain_text(str(notification.title))[:250]
        message = _plain_text(str(notification.message))[:1024]
        priority = _notification_priority(
            notification.priority,
            fallback=self.config.priority,
        )
        if not key or len(key) > 512 or "\n" in key:
            raise NotificationError("notification_key_invalid")
        if category not in MIRRORED_CATEGORIES:
            raise NotificationError("notification_category_not_mirrored")
        if not message:
            raise NotificationError("notification_text_required")
        with self._state_lock():
            state = self._load()
            pending = state["pending"]
            delivered = state["delivered"]
            if key in pending or key in delivered:
                return False
            pending[key] = {
                "category": category,
                "title": title,
                "message": message,
                "priority": priority,
                "queuedAt": _timestamp(),
            }
            self._save(state)
        return True

    def notify(self, notification: TextNotification) -> bool:
        created = self.enqueue(notification)
        if self.config.enabled and self.config.delivery_mode == "inline":
            self.deliver_pending()
        return created

    def deliver_pending(self, *, limit: int = 20) -> int:
        if not self.config.enabled:
            return 0
        with self._delivery_lock:
            return self._deliver_pending(limit=limit)

    def _deliver_pending(self, *, limit: int) -> int:
        delivered_count = 0
        for _index in range(max(0, limit)):
            with self._state_lock():
                state = self._load()
                pending = state["pending"]
                if not pending:
                    break
                key = next(iter(pending))
                record = pending[key]
            if not isinstance(record, dict):
                with self._state_lock():
                    state = self._load()
                    state["pending"].pop(key, None)
                    self._save(state)
                continue
            notification = TextNotification(
                key=key,
                category=str(record.get("category") or ""),
                title=str(record.get("title") or ""),
                message=str(record.get("message") or ""),
                priority=_notification_priority(
                    record.get("priority"),
                    fallback=self.config.priority,
                ),
            )
            try:
                self.client.send(notification)
            except Exception as exc:
                with self._state_lock():
                    state = self._load()
                    state["lastError"] = f"{type(exc).__name__}: {exc}"
                    self._save(state)
                raise NotificationError("pushover_pending_delivery_failed") from exc
            delivered_at = _timestamp()
            with self._state_lock():
                state = self._load()
                record = state["pending"].pop(key, None)
                if record is not None:
                    state["delivered"][key] = {
                        "category": notification.category,
                        "priority": notification.priority,
                        "at": delivered_at,
                    }
                    if len(state["delivered"]) > 2000:
                        retained = list(state["delivered"].items())[-2000:]
                        state["delivered"] = dict(retained)
                    state["lastDeliveryAt"] = delivered_at
                    state["lastError"] = ""
                    self._save(state)
                    delivered_count += 1
        return delivered_count

    def status(self) -> dict[str, object]:
        with self._state_lock():
            state = self._load()
        return {
            "enabled": self.config.enabled,
            "configured": bool(
                self.config.enabled and self.config.app_token and self.config.user_key
            ),
            "priority": self.config.priority,
            "defaultPriority": self.config.priority,
            "statePath": str(self.config.state_path),
            "pendingCount": len(state["pending"]),
            "deliveredCount": len(state["delivered"]),
            "lastDeliveryAt": str(state.get("lastDeliveryAt") or ""),
            "lastError": str(state.get("lastError") or ""),
            "deliveryMode": self.config.delivery_mode,
            "deliveryOwner": (
                "governor-worker"
                if self.config.delivery_mode == "worker"
                else "inline-producer"
            ),
            "mirroredCategories": sorted(MIRRORED_CATEGORIES),
            "tasksMirrored": False,
        }
