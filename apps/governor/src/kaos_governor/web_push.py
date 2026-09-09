from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Callable, Iterator, Mapping
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .notifications import (
    NotificationError,
    TextNotification,
    _atomic_json,
    _bool,
    _int,
    _normalized_notification,
    _secret,
    _timestamp,
)


ALLOWED_PUSH_HOSTS = frozenset(
    {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    }
)
GENERIC_MESSAGES = {
    "daily": "Daily update ready.",
    "fax": "Fax needs attention.",
    "mail": "Mail needs attention.",
    "maintenance": "Maintenance needs attention.",
    "system": "System needs attention.",
}


class WebPushError(NotificationError):
    pass


class WebPushDeliveryError(WebPushError):
    def __init__(self, code: str, status: int = 0) -> None:
        super().__init__(code)
        self.status = status


@dataclass(frozen=True)
class WebPushConfig:
    enabled: bool = False
    subscriptions_path: Path = Path("/data/notifications/web-push-subscriptions.json")
    outbox_path: Path = Path("/data/notifications/web-push-outbox.json")
    private_key: str = ""
    subject: str = ""
    timeout_seconds: int = 10

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "WebPushConfig":
        source = os.environ if env is None else env
        enabled = _bool(source, "WEB_PUSH_ENABLED")
        private_key = _secret(source, "WEB_PUSH_VAPID_PRIVATE_KEY") if enabled else ""
        subject = source.get("WEB_PUSH_VAPID_SUBJECT", "").strip() if enabled else ""
        if enabled and not private_key:
            raise WebPushError("WEB_PUSH_VAPID_PRIVATE_KEY is required when WEB_PUSH_ENABLED=true")
        if enabled and not (subject.startswith("mailto:") or subject.startswith("https://")):
            raise WebPushError("WEB_PUSH_VAPID_SUBJECT must start with mailto: or https://")
        config = cls(
            enabled=enabled,
            subscriptions_path=Path(
                source.get(
                    "WEB_PUSH_SUBSCRIPTIONS_PATH",
                    "/data/notifications/web-push-subscriptions.json",
                )
            ),
            outbox_path=Path(
                source.get(
                    "WEB_PUSH_OUTBOX_PATH",
                    "/data/notifications/web-push-outbox.json",
                )
            ),
            private_key=private_key,
            subject=subject,
            timeout_seconds=_int(source, "WEB_PUSH_TIMEOUT_SECONDS", 10, 1),
        )
        if enabled:
            config.public_key()
        return config

    def public_key(self) -> str:
        if not self.private_key:
            return ""
        key = self._ec_private_key()
        numbers = key.public_key().public_numbers()
        uncompressed = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
        return base64.urlsafe_b64encode(uncompressed).decode("ascii").rstrip("=")

    def encoded_private_key(self) -> str:
        """Return the RFC 8292 raw P-256 scalar expected by py-vapid."""
        if not self.private_key:
            return ""
        value = self._ec_private_key().private_numbers().private_value.to_bytes(32, "big")
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    def _ec_private_key(self) -> ec.EllipticCurvePrivateKey:
        try:
            key = serialization.load_pem_private_key(
                self.private_key.encode("utf-8"),
                password=None,
            )
        except (TypeError, ValueError) as exc:
            raise WebPushError("web_push_vapid_private_key_invalid") from exc
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise WebPushError("web_push_vapid_private_key_invalid")
        return key


def _subscription_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:24]


def _base64url(value: object, *, name: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or not all(
        character.isalnum() or character in {"-", "_"} for character in text
    ):
        raise WebPushError(f"web_push_{name}_invalid")
    padded = text + "=" * (-len(text) % 4)
    try:
        base64.urlsafe_b64decode(padded.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise WebPushError(f"web_push_{name}_invalid") from exc
    return text.rstrip("=")


def normalize_subscription(value: Mapping[str, object]) -> dict[str, object]:
    endpoint = str(value.get("endpoint") or "").strip()
    if not endpoint or len(endpoint) > 4096:
        raise WebPushError("web_push_endpoint_invalid")
    try:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise WebPushError("web_push_endpoint_invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise WebPushError("web_push_endpoint_invalid")
    if host not in ALLOWED_PUSH_HOSTS and not host.endswith(".push.apple.com"):
        raise WebPushError("web_push_endpoint_not_allowed")
    keys = value.get("keys")
    if not isinstance(keys, Mapping):
        raise WebPushError("web_push_keys_invalid")
    p256dh = _base64url(keys.get("p256dh"), name="p256dh", maximum=512)
    auth = _base64url(keys.get("auth"), name="auth", maximum=128)
    return {
        "id": _subscription_id(endpoint),
        "endpoint": endpoint,
        "expirationTime": value.get("expirationTime"),
        "keys": {"p256dh": p256dh, "auth": auth},
    }


class WebPushSubscriptionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    @contextmanager
    def _state_lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        with self._lock, lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, object]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        state["subscriptions"] = (
            state.get("subscriptions") if isinstance(state.get("subscriptions"), dict) else {}
        )
        return state

    def _save(self, state: dict[str, object]) -> None:
        state["version"] = 1
        _atomic_json(self.path, state)

    def upsert(self, value: Mapping[str, object]) -> dict[str, object]:
        normalized = normalize_subscription(value)
        subscription_id = str(normalized["id"])
        with self._state_lock():
            state = self._load()
            existing = state["subscriptions"].get(subscription_id)
            normalized["createdAt"] = (
                str(existing.get("createdAt") or "") if isinstance(existing, dict) else ""
            ) or _timestamp()
            normalized["updatedAt"] = _timestamp()
            state["subscriptions"][subscription_id] = normalized
            self._save(state)
        return {"id": subscription_id, "createdAt": normalized["createdAt"]}

    def remove(self, subscription_id: str) -> bool:
        if not isinstance(subscription_id, str) or not len(subscription_id) == 24:
            raise WebPushError("web_push_subscription_id_invalid")
        with self._state_lock():
            state = self._load()
            removed = state["subscriptions"].pop(subscription_id, None) is not None
            if removed:
                self._save(state)
        return removed

    def list(self) -> list[dict[str, object]]:
        with self._state_lock():
            state = self._load()
        return [dict(item) for item in state["subscriptions"].values() if isinstance(item, dict)]

    def get(self, subscription_id: str) -> dict[str, object] | None:
        return next((item for item in self.list() if item.get("id") == subscription_id), None)


class WebPushClient:
    def __init__(self, config: WebPushConfig, *, sender: Callable[..., object] | None = None) -> None:
        self.config = config
        self._sender = sender

    def send(self, subscription: Mapping[str, object], payload: Mapping[str, object]) -> None:
        if self._sender is None:
            try:
                from pywebpush import WebPushException, webpush
            except ImportError as exc:
                raise WebPushDeliveryError("web_push_library_unavailable") from exc
            sender = webpush
        else:
            WebPushException = Exception  # type: ignore[misc,assignment]
            sender = self._sender
        try:
            sender(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": subscription["keys"],
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=self.config.encoded_private_key(),
                vapid_claims={"sub": self.config.subject},
                timeout=self.config.timeout_seconds,
            )
        except WebPushDeliveryError:
            raise
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status = int(getattr(response, "status_code", 0) or 0)
            raise WebPushDeliveryError("web_push_delivery_failed", status) from exc
        except Exception as exc:
            raise WebPushDeliveryError("web_push_delivery_failed") from exc


class WebPushService:
    def __init__(
        self,
        config: WebPushConfig,
        *,
        store: WebPushSubscriptionStore | None = None,
        client: WebPushClient | None = None,
    ) -> None:
        self.config = config
        self.store = store or WebPushSubscriptionStore(config.subscriptions_path)
        self.client = client or WebPushClient(config)
        self._lock = threading.RLock()
        self._delivery_lock = threading.Lock()

    @contextmanager
    def _state_lock(self) -> Iterator[None]:
        self.config.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.config.outbox_path.with_name(f"{self.config.outbox_path.name}.lock")
        with self._lock, lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, object]:
        try:
            state = json.loads(self.config.outbox_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        state["pending"] = state.get("pending") if isinstance(state.get("pending"), dict) else {}
        state["delivered"] = state.get("delivered") if isinstance(state.get("delivered"), dict) else {}
        return state

    def _save(self, state: dict[str, object]) -> None:
        state["version"] = 1
        _atomic_json(self.config.outbox_path, state)

    def subscribe(self, value: Mapping[str, object]) -> dict[str, object]:
        if not self.config.enabled:
            raise WebPushError("web_push_disabled")
        return self.store.upsert(value)

    def unsubscribe(self, subscription_id: str) -> bool:
        removed = self.store.remove(subscription_id)
        with self._state_lock():
            state = self._load()
            changed = False
            for key, record in list(state["pending"].items()):
                if not isinstance(record, dict):
                    continue
                targets = [target for target in record.get("targets", []) if target != subscription_id]
                changed = changed or targets != record.get("targets", [])
                if targets:
                    record["targets"] = targets
                else:
                    state["pending"].pop(key, None)
            if changed:
                self._save(state)
        return removed

    def enqueue(self, notification: TextNotification) -> bool:
        if not self.config.enabled:
            return False
        normalized = _normalized_notification(notification, fallback_priority=0)
        targets = [str(item["id"]) for item in self.store.list()]
        if not targets:
            return False
        with self._state_lock():
            state = self._load()
            if normalized.key in state["pending"] or normalized.key in state["delivered"]:
                return False
            state["pending"][normalized.key] = {
                "category": normalized.category,
                "priority": normalized.priority,
                "targets": targets,
                "queuedAt": _timestamp(),
            }
            self._save(state)
        return True

    @staticmethod
    def _payload(key: str, category: str, priority: int) -> dict[str, object]:
        return {
            "title": "KaosGDD",
            "body": GENERIC_MESSAGES.get(category, "Something needs attention."),
            "tag": f"kaos-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}",
            "url": "/#/notifications",
            "icon": "/icons/main/android-chrome-192x192.png",
            "badge": "/icons/main/android-chrome-192x192.png",
            "priority": priority,
        }

    def deliver_pending(self, *, limit: int = 20) -> int:
        if not self.config.enabled:
            return 0
        with self._delivery_lock:
            delivered_count = 0
            for _index in range(max(0, limit)):
                with self._state_lock():
                    state = self._load()
                    if not state["pending"]:
                        break
                    key = next(iter(state["pending"]))
                    record = state["pending"][key]
                if not isinstance(record, dict):
                    with self._state_lock():
                        state = self._load()
                        state["pending"].pop(key, None)
                        self._save(state)
                    continue
                targets = list(record.get("targets") or [])
                category = str(record.get("category") or "system")
                priority = int(record.get("priority") or 0)
                if targets:
                    subscription_id = str(targets[0])
                    subscription = self.store.get(subscription_id)
                    if subscription is not None:
                        try:
                            self.client.send(subscription, self._payload(key, category, priority))
                        except WebPushDeliveryError as exc:
                            if exc.status not in {404, 410}:
                                with self._state_lock():
                                    failed = self._load()
                                    failed["lastError"] = str(exc)
                                    self._save(failed)
                                raise
                            self.store.remove(subscription_id)
                    with self._state_lock():
                        state = self._load()
                        current = state["pending"].get(key)
                        if isinstance(current, dict):
                            current["targets"] = [target for target in current.get("targets", []) if target != subscription_id]
                            self._save(state)
                    continue
                with self._state_lock():
                    state = self._load()
                    if state["pending"].pop(key, None) is not None:
                        state["delivered"][key] = {"category": category, "at": _timestamp()}
                        if len(state["delivered"]) > 2000:
                            state["delivered"] = dict(list(state["delivered"].items())[-2000:])
                        state["lastDeliveryAt"] = _timestamp()
                        state["lastError"] = ""
                        self._save(state)
                        delivered_count += 1
            return delivered_count

    def send_test(self, subscription_id: str = "") -> int:
        if not self.config.enabled:
            raise WebPushError("web_push_disabled")
        subscriptions = self.store.list()
        if subscription_id:
            subscriptions = [item for item in subscriptions if item.get("id") == subscription_id]
        if not subscriptions:
            raise WebPushError("web_push_subscription_not_found")
        payload = {
            "title": "KaosGDD",
            "body": "Web Push is working.",
            "tag": "kaos-web-push-test",
            "url": "/#/notifications",
            "icon": "/icons/main/android-chrome-192x192.png",
            "badge": "/icons/main/android-chrome-192x192.png",
            "priority": 0,
        }
        sent = 0
        for subscription in subscriptions:
            try:
                self.client.send(subscription, payload)
                sent += 1
            except WebPushDeliveryError as exc:
                if exc.status not in {404, 410}:
                    raise
                self.store.remove(str(subscription["id"]))
        return sent

    def status(self) -> dict[str, object]:
        state = self._load() if self.config.enabled else {"pending": {}, "delivered": {}}
        subscriptions = self.store.list() if self.config.enabled else []
        return {
            "enabled": self.config.enabled,
            "configured": bool(self.config.enabled and self.config.private_key and self.config.subject),
            "publicKey": self.config.public_key() if self.config.enabled else "",
            "subscriptionCount": len(subscriptions),
            "pendingCount": len(state["pending"]),
            "deliveredCount": len(state["delivered"]),
            "lastDeliveryAt": str(state.get("lastDeliveryAt") or ""),
            "lastError": str(state.get("lastError") or ""),
        }
