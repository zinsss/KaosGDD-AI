from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


PDF_CONTENT_TYPES = {"application/pdf", "application/octet-stream", ""}


class DocumentIntakeError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PaperlessConfig:
    base_url: str
    api_token: str
    timeout_seconds: float = 60.0
    max_document_bytes: int = 20 * 1024 * 1024
    public_url: str = ""
    default_owner_id: int = 0
    user_agent: str = "KaosGovernor/paperless-intake"

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> "PaperlessConfig":
        env = os.environ if source is None else source
        token = secret_value(env, "PAPERLESS_API_TOKEN")
        max_mb = max(1, int(env.get("PAPERLESS_INBOX_MAX_ATTACHMENT_MB", "20")))
        return cls(
            base_url=(env.get("PAPERLESS_BASE_URL") or env.get("PAPERLESS_INTERNAL_URL") or "").strip(),
            api_token=token,
            timeout_seconds=float(env.get("PAPERLESS_TIMEOUT_SECONDS", "60")),
            max_document_bytes=max_mb * 1024 * 1024,
            public_url=(env.get("PAPERLESS_PUBLIC_URL") or "").strip().rstrip("/"),
            default_owner_id=optional_positive_int(env.get("PAPERLESS_DEFAULT_OWNER_ID", "")),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_token)


@dataclass(frozen=True)
class PaperlessResult:
    ok: bool
    task_id: str
    filename: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "taskId": self.task_id,
            "filename": self.filename,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
        }


@dataclass(frozen=True)
class PaperlessTask:
    task_id: str
    status: str
    related_document_ids: tuple[int, ...] = ()

    @property
    def done(self) -> bool:
        return self.status.casefold() in {"success", "failure", "revoked"}

    @property
    def success(self) -> bool:
        return self.status.casefold() == "success"


@dataclass(frozen=True)
class PaperlessSearchResult:
    document_id: int
    title: str
    created: str
    filename: str
    correspondent: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.document_id,
            "title": self.title,
            "created": self.created,
            "filename": self.filename,
            "correspondent": self.correspondent,
        }


@dataclass(frozen=True)
class PaperlessDocument:
    document_id: int
    title: str
    created: str
    filename: str
    correspondent: str = ""
    content: str = ""
    tag_ids: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.document_id,
            "title": self.title,
            "created": self.created,
            "filename": self.filename,
            "correspondent": self.correspondent,
            "content": self.content,
            "tagIds": list(self.tag_ids),
        }


@dataclass(frozen=True)
class PaperlessTag:
    tag_id: int
    name: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.tag_id,
            "name": self.name,
        }


@dataclass(frozen=True)
class PaperlessSearchPage:
    query: str
    results: tuple[PaperlessSearchResult, ...]
    result_count: int
    total_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "results": [result.as_dict() for result in self.results],
            "resultCount": self.result_count,
            "totalCount": self.total_count,
        }


class PaperlessDocumentService:
    def __init__(
        self,
        config: PaperlessConfig,
        *,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self._urlopen = urlopen or urllib.request.urlopen
        self.last_submit_at = ""
        self.last_search_at = ""
        self.last_error = ""
        self.submitted_count = 0
        self.last_result_count = 0

    def search(self, query: object, *, limit: int = 5) -> list[PaperlessSearchResult]:
        return list(self.search_page(query, limit=limit).results)

    def task(self, task_id: object) -> PaperlessTask:
        if not self.config.enabled:
            raise DocumentIntakeError("paperless_not_configured")
        normalized = " ".join(str(task_id or "").split())
        if not normalized:
            raise DocumentIntakeError("paperless_task_id_required")
        try:
            payload = self._request_tasks({"task_id": normalized, "page_size": "1"})
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_task_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc
        results = decode_results_payload(payload)
        if not results:
            raise DocumentIntakeError("paperless_task_not_found")
        return paperless_task(results[0])

    def get(self, document_id: object) -> PaperlessDocument:
        if not self.config.enabled:
            raise DocumentIntakeError("paperless_not_configured")
        normalized_id = normalize_document_id(document_id)
        try:
            payload = self._request_document(normalized_id)
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc
        self.last_error = ""
        return paperless_document(payload)

    def update_metadata(
        self,
        document_id: object,
        *,
        title: str,
        tags: Sequence[str] = (),
    ) -> PaperlessDocument:
        if not self.config.enabled:
            raise DocumentIntakeError("paperless_not_configured")
        normalized_id = normalize_document_id(document_id)
        normalized_title = " ".join(str(title or "").split())
        if not normalized_title:
            raise DocumentIntakeError("paperless_title_required")
        tag_ids = self.ensure_tags(tags) if tags else []
        payload = {"title": normalized_title, "tags": tag_ids}
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/documents/{normalized_id}/",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="PATCH",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
            if response.status < 200 or response.status >= 300:
                raise DocumentIntakeError(f"paperless_http_{response.status}")
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc
        self.last_error = ""
        return paperless_document(decode_payload(body))

    def metadata_proposal(
        self,
        document_id: object,
        *,
        title: str = "",
        tags: Sequence[str] = (),
    ) -> dict[str, object]:
        document = self.get(document_id)
        proposed_title = " ".join(str(title or document.title).split())
        proposed_tags = tuple(clean_tag_name(tag) for tag in tags if clean_tag_name(tag))
        return {
            "document": document.as_dict(),
            "proposal": {
                "id": document.document_id,
                "oldTitle": document.title,
                "title": proposed_title,
                "tags": list(dict.fromkeys(proposed_tags)),
            },
        }

    def search_page(self, query: object, *, limit: int = 5) -> PaperlessSearchPage:
        if not self.config.enabled:
            raise DocumentIntakeError("paperless_not_configured")
        normalized = normalize_search_query(query)
        if not normalized:
            raise DocumentIntakeError("paperless_query_required")
        if limit <= 0 or limit > 25:
            raise DocumentIntakeError("paperless_limit_invalid")
        try:
            payload = self._request_documents({"query": normalized, "page_size": str(limit), "ordering": "-created"})
            results = tuple(paperless_search_result(item) for item in decode_results_payload(payload))[:limit]
            result_count = result_count_from_payload(payload, len(results))
            total_payload = self._request_documents({"page_size": "1"})
            total_count = result_count_from_payload(total_payload, 0)
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc
        self.last_search_at = _now()
        self.last_result_count = result_count
        self.last_error = ""
        return PaperlessSearchPage(normalized, results, result_count, total_count)

    def submit_pdf(
        self,
        filename: str,
        content: bytes,
        *,
        title: str = "",
        tags: Sequence[str] = (),
        source: str = "discord",
    ) -> PaperlessResult:
        if not self.config.enabled:
            raise DocumentIntakeError("paperless_not_configured")
        if not str(filename or "").lower().endswith(".pdf"):
            raise DocumentIntakeError("pdf_attachment_required")
        clean = clean_filename(filename)
        validate_pdf(clean, content, self.config.max_document_bytes)
        tag_ids = self.ensure_tags(tags) if tags else []
        fields: dict[str, str | list[str]] = {
            "title": title or Path(clean).stem,
            "created": "",
            "archive_serial_number": "",
            "custom_fields": "[]",
            "from_webui": "false",
        }
        if self.config.default_owner_id > 0:
            fields["owner"] = str(self.config.default_owner_id)
        if tag_ids:
            fields["tags"] = [str(value) for value in tag_ids]
        body, content_type = multipart_body(fields, "document", clean, content, "application/pdf")
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/documents/post_document/",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Content-Type": content_type,
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_body = response.read()
            if response.status < 200 or response.status >= 300:
                raise DocumentIntakeError(f"paperless_http_{response.status}")
            task_id = decode_task_id(response_body)
            self.submitted_count += 1
            self.last_error = ""
            return PaperlessResult(
                ok=True,
                task_id=task_id,
                filename=clean,
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
            )
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc

    def ensure_tags(self, names: Sequence[str]) -> list[int]:
        tag_ids: list[int] = []
        seen: set[str] = set()
        for raw_name in names:
            name = clean_tag_name(raw_name)
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            tag_ids.append(self._ensure_tag(name))
        return tag_ids

    def list_tags(self) -> tuple[PaperlessTag, ...]:
        if not self.config.enabled:
            raise DocumentIntakeError("paperless_not_configured")
        query = urllib.parse.urlencode({"page_size": "200", "ordering": "name"})
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/tags/?{query}",
            method="GET",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
            if response.status < 200 or response.status >= 300:
                raise DocumentIntakeError(f"paperless_tag_http_{response.status}")
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_tag_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc
        return tuple(paperless_tag(item) for item in decode_results(body) if paperless_tag(item).tag_id > 0)

    def existing_tag_names(self, names: Sequence[str]) -> tuple[str, ...]:
        requested = tuple(clean_tag_name(name) for name in names if clean_tag_name(name))
        if not requested:
            return ()
        by_key = {tag.name.casefold(): tag.name for tag in self.list_tags()}
        existing: list[str] = []
        for name in requested:
            matched = by_key.get(name.casefold())
            if matched and matched not in existing:
                existing.append(matched)
        return tuple(existing)

    def _ensure_tag(self, name: str) -> int:
        existing = self._find_tag(name)
        if existing:
            return existing
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/tags/",
            data=json.dumps({"name": name, "match": "", "matching_algorithm": 0}).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
            if response.status < 200 or response.status >= 300:
                raise DocumentIntakeError(f"paperless_tag_http_{response.status}")
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_tag_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc
        tag_id = decode_resource_id(body)
        if not tag_id:
            raise DocumentIntakeError("paperless_tag_missing_id")
        return tag_id

    def _find_tag(self, name: str) -> int:
        query = urllib.parse.urlencode({"page_size": "100", "ordering": "name"})
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/tags/?{query}",
            method="GET",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
            if response.status < 200 or response.status >= 300:
                raise DocumentIntakeError(f"paperless_tag_http_{response.status}")
        except urllib.error.HTTPError as exc:
            self.last_error = f"paperless_tag_http_{exc.code}"
            raise DocumentIntakeError(self.last_error) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = "paperless_request_failed"
            raise DocumentIntakeError(self.last_error) from exc
        for item in decode_results(body):
            if str(item.get("name") or "").casefold() == name.casefold():
                try:
                    return int(item.get("id") or 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    def _request_documents(self, query: Mapping[str, str]) -> Mapping[str, object]:
        query_string = urllib.parse.urlencode(query)
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/documents/?{query_string}",
            method="GET",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = response.read()
        if response.status < 200 or response.status >= 300:
            raise DocumentIntakeError(f"paperless_http_{response.status}")
        return decode_payload(body)

    def _request_tasks(self, query: Mapping[str, str]) -> Mapping[str, object]:
        query_string = urllib.parse.urlencode(query)
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/tasks/?{query_string}",
            method="GET",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = response.read()
        if response.status < 200 or response.status >= 300:
            raise DocumentIntakeError(f"paperless_task_http_{response.status}")
        return decode_payload(body)

    def _request_document(self, document_id: int) -> Mapping[str, object]:
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/documents/{document_id}/",
            method="GET",
            headers={
                "Authorization": f"Token {self.config.api_token}",
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = response.read()
        if response.status < 200 or response.status >= 300:
            raise DocumentIntakeError(f"paperless_http_{response.status}")
        return decode_payload(body)

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "configured": self.config.enabled,
            "baseUrlConfigured": bool(self.config.base_url),
            "publicUrlConfigured": bool(self.config.public_url),
            "maxAttachmentMB": self.config.max_document_bytes // (1024 * 1024),
            "submittedCount": self.submitted_count,
            "lastSearchAt": self.last_search_at,
            "lastResultCount": self.last_result_count,
            "lastError": self.last_error,
        }


def secret_value(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise DocumentIntakeError(f"{name.lower()}_ambiguous")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DocumentIntakeError(f"{name.lower()}_file_unreadable") from exc


def clean_filename(value: str) -> str:
    filename = Path(str(value or "document.pdf").replace("\\", "/")).name
    filename = re.sub(r'[\x00-\x1f\x7f"\\/]+', "-", filename).strip(" .-")
    if not filename:
        filename = "document.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    return filename[:180]


def normalize_search_query(value: object) -> str:
    query = " ".join(str(value or "").split())
    if len(query) > 300:
        raise DocumentIntakeError("paperless_query_too_long")
    return query


def normalize_document_id(value: object) -> int:
    if isinstance(value, bool):
        raise DocumentIntakeError("paperless_document_id_invalid")
    try:
        document_id = int(value)
    except (TypeError, ValueError) as exc:
        raise DocumentIntakeError("paperless_document_id_invalid") from exc
    if document_id <= 0:
        raise DocumentIntakeError("paperless_document_id_invalid")
    return document_id


def optional_positive_int(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        number = int(text)
    except ValueError as exc:
        raise DocumentIntakeError("paperless_owner_id_invalid") from exc
    if number <= 0:
        raise DocumentIntakeError("paperless_owner_id_invalid")
    return number


def paperless_search_result(payload: Mapping[str, object]) -> PaperlessSearchResult:
    try:
        document_id = int(payload.get("id") or 0)
    except (TypeError, ValueError):
        document_id = 0
    title = str(payload.get("title") or payload.get("original_file_name") or f"Document {document_id}")
    filename = str(payload.get("original_file_name") or payload.get("archive_filename") or "")
    correspondent = payload.get("correspondent")
    if isinstance(correspondent, Mapping):
        correspondent_value = str(correspondent.get("name") or "")
    else:
        correspondent_value = str(payload.get("correspondent_name") or "")
    return PaperlessSearchResult(
        document_id=document_id,
        title=title,
        created=str(payload.get("created") or payload.get("created_date") or ""),
        filename=filename,
        correspondent=correspondent_value,
    )


def paperless_document(payload: Mapping[str, object]) -> PaperlessDocument:
    result = paperless_search_result(payload)
    raw_tags = payload.get("tags")
    tag_ids: list[int] = []
    if isinstance(raw_tags, list):
        for value in raw_tags:
            try:
                tag_id = int(value)
            except (TypeError, ValueError):
                continue
            if tag_id > 0 and tag_id not in tag_ids:
                tag_ids.append(tag_id)
    return PaperlessDocument(
        document_id=result.document_id,
        title=result.title,
        created=result.created,
        filename=result.filename,
        correspondent=result.correspondent,
        content=str(payload.get("content") or ""),
        tag_ids=tuple(tag_ids),
    )


def paperless_task(payload: Mapping[str, object]) -> PaperlessTask:
    document_ids: list[int] = []
    for raw_id in payload.get("related_document_ids") or ():
        try:
            document_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if document_id > 0:
            document_ids.append(document_id)
    return PaperlessTask(
        task_id=str(payload.get("task_id") or ""),
        status=str(payload.get("status") or ""),
        related_document_ids=tuple(document_ids),
    )


def paperless_tag(payload: Mapping[str, object]) -> PaperlessTag:
    try:
        tag_id = int(payload.get("id") or 0)
    except (TypeError, ValueError):
        tag_id = 0
    return PaperlessTag(tag_id, str(payload.get("name") or "").strip())


def validate_pdf(filename: str, content: bytes, max_bytes: int) -> None:
    if not filename.lower().endswith(".pdf"):
        raise DocumentIntakeError("pdf_attachment_required")
    if not content or len(content) > max_bytes:
        raise DocumentIntakeError("pdf_size_invalid")
    if not content.startswith(b"%PDF-"):
        raise DocumentIntakeError("invalid_pdf_signature")


def multipart_body(
    fields: Mapping[str, str | Sequence[str]],
    file_field: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    boundary = f"KaosGovernor{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        values = value if isinstance(value, list | tuple) else (value,)
        for item in values:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                    str(item).encode("utf-8"),
                    b"\r\n",
                ]
            )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename.replace(chr(34), "-")}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def decode_task_id(body: bytes) -> str:
    raw = body.decode("utf-8", errors="replace").strip()
    if not raw:
        return ""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip('"')
    if isinstance(decoded, str):
        return decoded
    if isinstance(decoded, Mapping):
        return str(decoded.get("task_id") or decoded.get("taskId") or decoded.get("id") or "")
    return str(decoded)


def decode_resource_id(body: bytes) -> int:
    try:
        decoded = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return 0
    if isinstance(decoded, Mapping):
        try:
            return int(decoded.get("id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def decode_results(body: bytes) -> list[Mapping[str, object]]:
    return decode_results_payload(decode_payload(body))


def decode_payload(body: bytes) -> Mapping[str, object]:
    try:
        decoded = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, Mapping) else {"results": decoded}


def decode_results_payload(decoded: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw_results = decoded.get("results") if isinstance(decoded, Mapping) else decoded
    if not isinstance(raw_results, list):
        return []
    return [item for item in raw_results if isinstance(item, Mapping)]


def result_count_from_payload(payload: Mapping[str, object], fallback: int) -> int:
    value = payload.get("count")
    try:
        count = int(value)
    except (TypeError, ValueError):
        return fallback
    return count if count >= 0 else fallback


def clean_tag_name(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f#]+", "", str(value or "")).strip()
    return cleaned[:100]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
