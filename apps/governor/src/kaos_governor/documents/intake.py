from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets
from typing import Mapping


DEFAULT_INTAKE_PATH = Path("/data/documents/intake.json")


@dataclass(frozen=True)
class DocumentInboxRecord:
    record_id: str
    submitted_at: str
    title: str
    filename: str
    sha256: str
    size_bytes: int
    task_id: str
    source: str = "pwa"
    status: str = "ocr_pending"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.record_id,
            "submittedAt": self.submitted_at,
            "title": self.title,
            "filename": self.filename,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "taskId": self.task_id,
            "source": self.source,
            "status": self.status,
        }


class DocumentIntakeStore:
    def __init__(self, path: Path = DEFAULT_INTAKE_PATH) -> None:
        self.path = path

    def list_records(self, *, limit: int = 100) -> list[DocumentInboxRecord]:
        records = sorted(self._read(), key=lambda item: item.submitted_at, reverse=True)
        return records[: max(1, min(int(limit), 250))]

    def find_active_by_sha(self, sha256: str) -> DocumentInboxRecord | None:
        needle = str(sha256 or "").strip().lower()
        if not needle:
            return None
        for record in self._read():
            if record.sha256 == needle and record.status != "failed" and record.task_id:
                return record
        return None

    def add_submitted(
        self,
        *,
        title: str,
        filename: str,
        content: bytes,
        task_id: str,
        source: str = "pwa",
    ) -> DocumentInboxRecord:
        now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        record = DocumentInboxRecord(
            record_id=f"doc-{now.replace('-', '').replace(':', '').replace('Z', '')}-{secrets.token_hex(3)}",
            submitted_at=now,
            title=clean_title(title) or clean_filename_stem(filename),
            filename=clean_filename(filename),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            task_id=str(task_id or ""),
            source=clean_source(source),
        )
        records = [item for item in self._read() if item.record_id != record.record_id]
        records.append(record)
        self._write(records)
        return record

    def _read(self) -> list[DocumentInboxRecord]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(payload, dict):
            return []
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            return []
        records: list[DocumentInboxRecord] = []
        for value in raw_records:
            record = record_from_json(value)
            if record:
                records.append(record)
        return records

    def _write(self, records: list[DocumentInboxRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "records": [record.as_dict() for record in sorted(records, key=lambda item: item.submitted_at, reverse=True)[:500]],
        }
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)


def record_from_json(value: object) -> DocumentInboxRecord | None:
    if not isinstance(value, Mapping):
        return None
    record_id = str(value.get("id") or value.get("recordId") or "").strip()
    task_id = str(value.get("taskId") or value.get("task_id") or "").strip()
    sha256 = str(value.get("sha256") or "").strip().lower()
    if not record_id or not sha256:
        return None
    try:
        size_bytes = max(0, int(value.get("sizeBytes") or value.get("size_bytes") or 0))
    except (TypeError, ValueError):
        size_bytes = 0
    return DocumentInboxRecord(
        record_id=record_id,
        submitted_at=str(value.get("submittedAt") or value.get("submitted_at") or ""),
        title=clean_title(str(value.get("title") or "")),
        filename=clean_filename(str(value.get("filename") or "")),
        sha256=sha256,
        size_bytes=size_bytes,
        task_id=task_id,
        source=clean_source(str(value.get("source") or "pwa")),
        status=clean_status(str(value.get("status") or "ocr_pending")),
    )


def clean_filename(value: str) -> str:
    name = Path(str(value or "document.pdf")).name.strip()
    return name or "document.pdf"


def clean_filename_stem(value: str) -> str:
    stem = Path(clean_filename(value)).stem.strip()
    return stem or "Document"


def clean_title(value: str) -> str:
    return " ".join(str(value or "").split())[:180]


def clean_source(value: str) -> str:
    source = "".join(ch for ch in str(value or "pwa").lower() if ch.isalnum() or ch in {"-", "_"})
    return source[:32] or "pwa"


def clean_status(value: str) -> str:
    status = str(value or "").strip().lower()
    return status if status in {"ocr_pending", "review", "archived", "failed"} else "ocr_pending"
