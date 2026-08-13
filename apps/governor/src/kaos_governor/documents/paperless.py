from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
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
        self.last_error = ""
        self.submitted_count = 0

    def submit_pdf(self, filename: str, content: bytes, *, title: str = "", source: str = "discord") -> PaperlessResult:
        if not self.config.enabled:
            raise DocumentIntakeError("paperless_not_configured")
        if not str(filename or "").lower().endswith(".pdf"):
            raise DocumentIntakeError("pdf_attachment_required")
        clean = clean_filename(filename)
        validate_pdf(clean, content, self.config.max_document_bytes)
        fields = {
            "title": title or Path(clean).stem,
            "created": "",
            "archive_serial_number": "",
            "custom_fields": "[]",
            "from_webui": "false",
        }
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

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "configured": self.config.enabled,
            "baseUrlConfigured": bool(self.config.base_url),
            "publicUrlConfigured": bool(self.config.public_url),
            "maxAttachmentMB": self.config.max_document_bytes // (1024 * 1024),
            "submittedCount": self.submitted_count,
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


def validate_pdf(filename: str, content: bytes, max_bytes: int) -> None:
    if not filename.lower().endswith(".pdf"):
        raise DocumentIntakeError("pdf_attachment_required")
    if not content or len(content) > max_bytes:
        raise DocumentIntakeError("pdf_size_invalid")
    if not content.startswith(b"%PDF-"):
        raise DocumentIntakeError("invalid_pdf_signature")


def multipart_body(
    fields: Mapping[str, str],
    file_field: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    boundary = f"KaosGovernor{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
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
