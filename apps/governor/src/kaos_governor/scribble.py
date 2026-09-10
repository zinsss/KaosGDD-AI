from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import fcntl
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from typing import Iterator, Mapping


MAX_SCRIBBLE_TEXT_CHARS = 100_000
MAX_SCRIBBLE_FILE_BYTES = 25 * 1024 * 1024
SCRIBBLE_RETENTION_DAYS = 30


class ScribbleError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ScribbleItem:
    item_id: str
    created_at: str
    updated_at: str
    source: str
    title: str
    text: str = ""
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0

    @property
    def has_file(self) -> bool:
        return bool(self.filename)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "expiresAt": _expiration_timestamp(self.created_at),
            "source": self.source,
            "kind": "file" if self.has_file else "text",
            "title": self.title,
            "text": self.text,
            "filename": self.filename,
            "contentType": self.content_type,
            "sizeBytes": self.size_bytes,
            "hasFile": self.has_file,
        }


class ScribbleStore:
    def __init__(self, index_path: Path = Path("/data/scribble/index.json")) -> None:
        self.index_path = index_path
        self.files_root = index_path.parent / "files"
        self.lock_path = index_path.parent / ".lock"
        self._thread_lock = threading.RLock()

    def list_items(self, *, limit: int = 100) -> list[ScribbleItem]:
        with self._locked():
            items = sorted(self._read_unlocked(), key=lambda item: item.created_at, reverse=True)
            return items[: max(1, min(int(limit), 250))]

    def get(self, item_id: str) -> ScribbleItem:
        normalized = _clean_id(item_id)
        with self._locked():
            return self._get_unlocked(normalized)

    def create(
        self,
        *,
        title: str = "",
        text: str = "",
        filename: str = "",
        content: bytes = b"",
        content_type: str = "",
        source: str = "pwa",
    ) -> ScribbleItem:
        clean_text = _clean_text(text)
        clean_filename = _clean_filename(filename) if content else ""
        if not clean_text and not content:
            raise ScribbleError("scribble_content_required")
        if len(content) > MAX_SCRIBBLE_FILE_BYTES:
            raise ScribbleError("scribble_file_too_large")
        if content and not clean_filename:
            clean_filename = "attachment"
        now = _timestamp()
        item_id = f"scribble-{now[:10].replace('-', '')}-{secrets.token_hex(4)}"
        clean_title = _clean_title(title) or (
            Path(clean_filename).stem if clean_filename else _first_line(clean_text)
        ) or "Untitled"
        clean_content_type = _clean_content_type(content_type, clean_filename)
        item = ScribbleItem(
            item_id=item_id,
            created_at=now,
            updated_at=now,
            source=_clean_source(source),
            title=clean_title,
            text=clean_text,
            filename=clean_filename,
            content_type=clean_content_type if content else "",
            size_bytes=len(content),
        )
        with self._locked():
            if content:
                self._write_file_unlocked(item, content)
            items = self._read_unlocked()
            items.append(item)
            self._write_unlocked(items)
        return item

    def update(self, item_id: str, *, title: str, text: str) -> ScribbleItem:
        normalized = _clean_id(item_id)
        with self._locked():
            items = self._read_unlocked()
            current = next((item for item in items if item.item_id == normalized), None)
            if current is None:
                raise ScribbleError("scribble_not_found")
            clean_text = _clean_text(text)
            if not clean_text and not current.has_file:
                raise ScribbleError("scribble_content_required")
            updated = replace(
                current,
                title=_clean_title(title) or current.title,
                text=clean_text,
                updated_at=_timestamp(),
            )
            self._write_unlocked([updated if item.item_id == normalized else item for item in items])
            return updated

    def delete(self, item_id: str) -> ScribbleItem:
        normalized = _clean_id(item_id)
        with self._locked():
            items = self._read_unlocked()
            current = next((item for item in items if item.item_id == normalized), None)
            if current is None:
                raise ScribbleError("scribble_not_found")
            self._write_unlocked([item for item in items if item.item_id != normalized])
            if current.has_file:
                self._delete_file_unlocked(current)
            return current

    def read_file(self, item_id: str) -> tuple[ScribbleItem, bytes]:
        normalized = _clean_id(item_id)
        with self._locked():
            item = self._get_unlocked(normalized)
            if not item.has_file:
                raise ScribbleError("scribble_file_not_found")
            try:
                content = self._file_path(item).read_bytes()
            except OSError as exc:
                raise ScribbleError("scribble_file_unavailable") from exc
            return item, content

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _get_unlocked(self, item_id: str) -> ScribbleItem:
        for item in self._read_unlocked():
            if item.item_id == item_id:
                return item
        raise ScribbleError("scribble_not_found")

    def _read_unlocked(self) -> list[ScribbleItem]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        values = payload.get("items") if isinstance(payload, Mapping) else []
        items = [item for value in values if (item := _from_json(value)) is not None]
        active = [item for item in items if not _is_expired(item.created_at)]
        if len(active) != len(items):
            for item in items:
                if item not in active and item.has_file:
                    self._delete_file_unlocked(item)
            self._write_unlocked(active)
        return active

    def _write_unlocked(self, items: list[ScribbleItem]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "items": [item.as_dict() for item in sorted(items, key=lambda value: value.created_at, reverse=True)[:500]],
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.index_path.parent,
            prefix=".scribble-",
            suffix=".tmp",
            delete=False,
        ) as output:
            json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
            temporary = Path(output.name)
        temporary.replace(self.index_path)

    def _write_file_unlocked(self, item: ScribbleItem, content: bytes) -> None:
        target = self._file_path(item)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp-{secrets.token_hex(3)}")
        temporary.write_bytes(content)
        temporary.replace(target)

    def _delete_file_unlocked(self, item: ScribbleItem) -> None:
        path = self._file_path(item)
        try:
            path.unlink()
            path.parent.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _file_path(self, item: ScribbleItem) -> Path:
        return self.files_root / item.item_id / item.filename


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_expired(value: str) -> bool:
    created_at = _parse_timestamp(value)
    if created_at is None:
        return False
    return created_at <= datetime.now(UTC) - timedelta(days=SCRIBBLE_RETENTION_DAYS)


def _expiration_timestamp(value: str) -> str:
    created_at = _parse_timestamp(value)
    if created_at is None:
        return ""
    return (created_at + timedelta(days=SCRIBBLE_RETENTION_DAYS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        created_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at.astimezone(UTC)


def _clean_id(value: object) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"scribble-[a-zA-Z0-9-]{8,80}", normalized):
        raise ScribbleError("scribble_not_found")
    return normalized


def _clean_title(value: object) -> str:
    return " ".join(str(value or "").split())[:200]


def _clean_text(value: object) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) > MAX_SCRIBBLE_TEXT_CHARS:
        raise ScribbleError("scribble_text_too_large")
    return text


def _first_line(value: str) -> str:
    return " ".join((value.splitlines() or [""])[0].split())[:200]


def _clean_filename(value: object) -> str:
    name = Path(str(value or "").replace("\\", "/")).name.replace("\x00", "").strip()
    return re.sub(r"[^0-9A-Za-z._()\-\u3131-\u318e\uac00-\ud7a3 ]+", "_", name)[:180]


def _clean_content_type(value: object, filename: str) -> str:
    candidate = str(value or "").split(";", 1)[0].strip().lower()
    if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", candidate):
        return candidate
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _clean_source(value: object) -> str:
    candidate = re.sub(r"[^a-z0-9_-]+", "", str(value or "").strip().lower())
    return candidate[:30] or "pwa"


def _from_json(value: object) -> ScribbleItem | None:
    if not isinstance(value, Mapping):
        return None
    try:
        item_id = _clean_id(value.get("id"))
    except ScribbleError:
        return None
    filename = _clean_filename(value.get("filename"))
    return ScribbleItem(
        item_id=item_id,
        created_at=str(value.get("createdAt") or ""),
        updated_at=str(value.get("updatedAt") or value.get("createdAt") or ""),
        source=_clean_source(value.get("source")),
        title=_clean_title(value.get("title")) or "Untitled",
        text=_clean_text(value.get("text")),
        filename=filename,
        content_type=_clean_content_type(value.get("contentType"), filename) if filename else "",
        size_bytes=max(0, int(value.get("sizeBytes") or 0)),
    )
