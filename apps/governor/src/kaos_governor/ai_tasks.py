from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
import threading
from typing import Mapping


DEFAULT_AI_TASK_ARCHIVE_PATH = Path("/data/ai-tasks/archive.json")
_ARCHIVE_LOCK = threading.Lock()


class AITaskError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AITaskRecord:
    task_id: str
    kind: str
    status: str
    prompt: str
    source: dict[str, object]
    memo: dict[str, object]
    provider: str
    created_at: str
    updated_at: str
    result: dict[str, object] | None = None
    error: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "prompt": self.prompt,
            "source": self.source,
            "memo": self.memo,
            "provider": self.provider,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "result": self.result or {},
            "error": self.error,
        }


class AITaskArchive:
    def __init__(self, path: Path = DEFAULT_AI_TASK_ARCHIVE_PATH) -> None:
        self.path = path

    def list_records(self, *, limit: int = 50) -> list[AITaskRecord]:
        records = sorted(self._read(), key=lambda item: item.created_at, reverse=True)
        return records[: max(1, min(int(limit), 250))]

    def add_preview(
        self,
        *,
        kind: str,
        prompt: str,
        source: Mapping[str, object],
        memo: Mapping[str, object],
        provider: str = "kaosbrain-openai",
    ) -> AITaskRecord:
        now = _now()
        record = AITaskRecord(
            task_id=f"ait-{now.replace('-', '').replace(':', '').replace('Z', '')}-{secrets.token_hex(3)}",
            kind=_clean_token(kind) or "official_doc_memo",
            status="previewed",
            prompt=_clean_text(prompt, 1200),
            source={str(key): value for key, value in source.items()},
            memo={str(key): value for key, value in memo.items()},
            provider=_clean_text(provider, 80),
            created_at=now,
            updated_at=now,
        )
        records = [item for item in self._read() if item.task_id != record.task_id]
        records.append(record)
        self._write(records)
        return record

    def add_running(
        self,
        *,
        kind: str,
        prompt: str,
        source: Mapping[str, object],
        provider: str = "kaosbrain-openai",
    ) -> AITaskRecord:
        now = _now()
        record = AITaskRecord(
            task_id=f"ait-{now.replace('-', '').replace(':', '').replace('Z', '')}-{secrets.token_hex(3)}",
            kind=_clean_token(kind) or "web",
            status="running",
            prompt=_clean_text(prompt, 1200),
            source={str(key): value for key, value in source.items()},
            memo={},
            provider=_clean_text(provider, 80),
            created_at=now,
            updated_at=now,
            result={},
            error="",
        )
        with _ARCHIVE_LOCK:
            records = [item for item in self._read_unlocked() if item.task_id != record.task_id]
            records.append(record)
            self._write_unlocked(records)
        return record

    def add_result(
        self,
        *,
        kind: str,
        prompt: str,
        source: Mapping[str, object],
        result: Mapping[str, object],
        provider: str = "kaosbrain-openai",
    ) -> AITaskRecord:
        now = _now()
        title = _clean_text(result.get("title"), 160) or _clean_text(prompt, 160) or "AI Task"
        content = str(result.get("content") or "").strip()
        record = AITaskRecord(
            task_id=f"ait-{now.replace('-', '').replace(':', '').replace('Z', '')}-{secrets.token_hex(3)}",
            kind=_clean_token(kind) or "web",
            status="previewed",
            prompt=_clean_text(prompt, 1200),
            source={str(key): value for key, value in source.items()},
            memo={"title": title, "content": content},
            provider=_clean_text(provider, 80),
            created_at=now,
            updated_at=now,
            result={str(key): value for key, value in result.items()},
            error="",
        )
        records = [item for item in self._read() if item.task_id != record.task_id]
        records.append(record)
        self._write(records)
        return record

    def finish_preview(
        self,
        task_id: str,
        *,
        source: Mapping[str, object],
        memo: Mapping[str, object],
        provider: str = "kaosbrain-openai",
    ) -> AITaskRecord:
        return self._replace(
            task_id,
            status="previewed",
            source={str(key): value for key, value in source.items()},
            memo={str(key): value for key, value in memo.items()},
            provider=_clean_text(provider, 80),
            result={},
            error="",
        )

    def finish_result(
        self,
        task_id: str,
        *,
        source: Mapping[str, object],
        result: Mapping[str, object],
        provider: str = "kaosbrain-openai",
    ) -> AITaskRecord:
        title = _clean_text(result.get("title"), 160) or "AI Task"
        content = str(result.get("content") or "").strip()
        return self._replace(
            task_id,
            status="previewed",
            source={str(key): value for key, value in source.items()},
            memo={"title": title, "content": content},
            provider=_clean_text(provider, 80),
            result={str(key): value for key, value in result.items()},
            error="",
        )

    def fail(self, task_id: str, *, error: str) -> AITaskRecord:
        return self._replace(task_id, status="failed", error=_clean_token(error) or "ai_task_failed")

    def complete(self, task_id: str, *, memo_name: str = "") -> AITaskRecord:
        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            raise AITaskError("ai_task_id_required")
        return self._replace(normalized_id, status="applied", result={"memoName": _clean_text(memo_name, 160)}, error="")

    def _replace(
        self,
        task_id: str,
        *,
        status: str | None = None,
        source: Mapping[str, object] | None = None,
        memo: Mapping[str, object] | None = None,
        provider: str | None = None,
        result: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> AITaskRecord:
        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            raise AITaskError("ai_task_id_required")
        with _ARCHIVE_LOCK:
            records = self._read_unlocked()
            updated: AITaskRecord | None = None
            now = _now()
            next_records: list[AITaskRecord] = []
            for record in records:
                if record.task_id != normalized_id:
                    next_records.append(record)
                    continue
                updated = AITaskRecord(
                    task_id=record.task_id,
                    kind=record.kind,
                    status=_clean_token(status) if status is not None else record.status,
                    prompt=record.prompt,
                    source={str(key): value for key, value in (source if source is not None else record.source).items()},
                    memo={str(key): value for key, value in (memo if memo is not None else record.memo).items()},
                    provider=_clean_text(provider, 80) if provider is not None else record.provider,
                    created_at=record.created_at,
                    updated_at=now,
                    result={str(key): value for key, value in (result if result is not None else record.result or {}).items()},
                    error=_clean_text(error, 200) if error is not None else record.error,
                )
                next_records.append(updated)
            if updated is None:
                raise AITaskError("ai_task_not_found")
            self._write_unlocked(next_records)
            return updated

    def _read(self) -> list[AITaskRecord]:
        with _ARCHIVE_LOCK:
            return self._read_unlocked()

    def _read_unlocked(self) -> list[AITaskRecord]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, Mapping):
            return []
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            return []
        return [record for item in raw_records if (record := _record_from_json(item))]

    def _write(self, records: list[AITaskRecord]) -> None:
        with _ARCHIVE_LOCK:
            self._write_unlocked(records)

    def _write_unlocked(self, records: list[AITaskRecord]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "records": [record.as_dict() for record in sorted(records, key=lambda item: item.created_at, reverse=True)[:500]],
            }
            temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            temporary_path.replace(self.path)
        except OSError as exc:
            raise AITaskError("ai_task_archive_write_failed") from exc


def _record_from_json(value: object) -> AITaskRecord | None:
    if not isinstance(value, Mapping):
        return None
    task_id = _clean_text(value.get("id") or value.get("taskId"), 80)
    kind = _clean_token(value.get("kind")) or "official_doc_memo"
    status = _clean_token(value.get("status")) or "previewed"
    created_at = _clean_text(value.get("createdAt") or value.get("created_at"), 40)
    if not task_id or not created_at:
        return None
    source = value.get("source") if isinstance(value.get("source"), Mapping) else {}
    memo = value.get("memo") if isinstance(value.get("memo"), Mapping) else {}
    result = value.get("result") if isinstance(value.get("result"), Mapping) else {}
    return AITaskRecord(
        task_id=task_id,
        kind=kind,
        status=status if status in {"running", "previewed", "applied", "failed"} else "previewed",
        prompt=_clean_text(value.get("prompt"), 1200),
        source={str(key): item for key, item in source.items()},
        memo={str(key): item for key, item in memo.items()},
        provider=_clean_text(value.get("provider"), 80),
        created_at=created_at,
        updated_at=_clean_text(value.get("updatedAt") or value.get("updated_at"), 40) or created_at,
        result={str(key): item for key, item in result.items()},
        error=_clean_text(value.get("error"), 200),
    )


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean_token(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"_", "-"})[:80]
