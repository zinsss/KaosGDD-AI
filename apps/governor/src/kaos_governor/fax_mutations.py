"""Confirmed, transport-neutral outbound fax mutations.

The HTTP/PWA/Shortcut layers only adapt authentication and request bodies.
This module owns document preparation, durable confirmation, idempotency,
short-lived staging, and the single handoff to :class:`FaxService`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import timedelta
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from .durable import Actor, DurableGovernorError, OperationRequest, PendingOperationPayload
from .fax import FaxError, FaxService, request_from_pdf, safe_name
from .operations import GovernorOperations, OperationProposal


FAX_CONFIRMATION_TTL = timedelta(minutes=10)
FAX_STAGE_MAX_AGE_SECONDS = 60 * 60
FAX_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"})
FAX_STAGE_NAME = re.compile(r"^[0-9a-f]{64}\.pdf$")
FAX_PENDING_KIND = "fax.send"


@dataclass(frozen=True)
class PreparedFaxDocument:
    filename: str
    content: bytes
    sha256: str
    size_bytes: int
    page_count: int


@dataclass(frozen=True)
class PendingFaxSend:
    destination: str
    sender: str
    source_id: str
    filename: str
    sha256: str
    size_bytes: int
    page_count: int
    staged_filename: str


@dataclass(frozen=True)
class FaxSendProposal:
    operation: OperationProposal
    pending: PendingFaxSend


def _image_to_pdf(filename: str, content: bytes) -> tuple[str, bytes]:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.seek(0)
            if image.mode in {"RGBA", "LA", "P"}:
                converted = image.convert("RGBA")
                page = Image.new("RGB", image.size, "white")
                page.paste(converted, mask=converted.getchannel("A"))
            else:
                page = image.convert("RGB")
            output = io.BytesIO()
            page.save(output, format="PDF", resolution=200.0)
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError) as exc:
        raise FaxError("image_attachment_invalid") from exc
    stem = Path(filename).stem.strip(" .-") or "fax"
    return f"{stem}.pdf", output.getvalue()


def _pdf_page_count(content: bytes) -> int:
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    raise FaxError("encrypted_pdf_not_supported")
            except FaxError:
                raise
            except Exception as exc:
                raise FaxError("encrypted_pdf_not_supported") from exc
        pages = len(reader.pages)
    except FaxError:
        raise
    except Exception as exc:
        raise FaxError("invalid_pdf_document") from exc
    if pages <= 0 or pages > 500:
        raise FaxError("fax_page_count_invalid")
    return pages


def prepare_fax_document(filename: str, content: bytes, *, max_bytes: int) -> PreparedFaxDocument:
    clean_name = safe_name(filename or "fax.pdf")
    if not content:
        raise FaxError("pdf_size_invalid")
    suffix = Path(clean_name).suffix.lower()
    if suffix == ".pdf":
        pdf = bytes(content)
    elif suffix in FAX_IMAGE_EXTENSIONS:
        clean_name, pdf = _image_to_pdf(clean_name, content)
    else:
        raise FaxError("fax_attachment_required")
    if len(pdf) > max_bytes:
        raise FaxError("pdf_size_invalid")
    if not pdf.startswith(b"%PDF-"):
        raise FaxError("invalid_pdf_signature")
    page_count = _pdf_page_count(pdf)
    return PreparedFaxDocument(
        filename=clean_name,
        content=pdf,
        sha256=hashlib.sha256(pdf).hexdigest(),
        size_bytes=len(pdf),
        page_count=page_count,
    )


def pending_fax_record(pending: PendingFaxSend) -> tuple[str, dict[str, Any]]:
    return FAX_PENDING_KIND, asdict(pending)


def pending_fax_from_record(record: PendingOperationPayload) -> PendingFaxSend:
    if record.schema_version != 1 or record.payload_kind != FAX_PENDING_KIND:
        raise DurableGovernorError("operation_payload_kind_unknown")
    values = dict(record.payload)
    try:
        pending = PendingFaxSend(**values)
    except (TypeError, ValueError) as exc:
        raise DurableGovernorError("operation_payload_invalid") from exc
    if not FAX_STAGE_NAME.fullmatch(pending.staged_filename):
        raise DurableGovernorError("operation_payload_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", pending.sha256):
        raise DurableGovernorError("operation_payload_invalid")
    if pending.size_bytes <= 0 or pending.page_count <= 0:
        raise DurableGovernorError("operation_payload_invalid")
    return pending


def fax_preview_payload(pending: PendingFaxSend) -> dict[str, object]:
    return {
        "destination": pending.destination,
        "filename": pending.filename,
        "sizeBytes": pending.size_bytes,
        "pageCount": pending.page_count,
        "sha256": pending.sha256,
    }


class FaxMutationService:
    """Create and approve exact outbound fax proposals."""

    def __init__(
        self,
        fax: FaxService,
        operations: GovernorOperations,
        stage_root: Path,
        *,
        confirmation_ttl: timedelta = FAX_CONFIRMATION_TTL,
        stage_max_age_seconds: int = FAX_STAGE_MAX_AGE_SECONDS,
    ) -> None:
        if confirmation_ttl <= timedelta():
            raise FaxError("fax_confirmation_ttl_invalid")
        if stage_max_age_seconds <= 0:
            raise FaxError("fax_stage_max_age_invalid")
        self.fax = fax
        self.operations = operations
        self.stage_root = stage_root
        self.confirmation_ttl = confirmation_ttl
        self.stage_max_age_seconds = stage_max_age_seconds

    def _ensure_enabled(self) -> None:
        if not self.fax.config.enabled:
            raise FaxError("fax_send_disabled")
        if self.fax.config.transport == "connector" and not (
            self.fax.config.connector_base_url and self.fax.config.connector_token
        ):
            raise FaxError("fax_connector_not_configured")

    def _ensure_stage_root(self) -> None:
        self.stage_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.stage_root, 0o700)
        except PermissionError:
            pass

    def cleanup_staged(self, *, now: float | None = None) -> int:
        timestamp = time.time() if now is None else now
        try:
            candidates = tuple(self.stage_root.glob("*.pdf"))
        except OSError:
            return 0
        deleted = 0
        for candidate in candidates:
            if not FAX_STAGE_NAME.fullmatch(candidate.name):
                continue
            try:
                if timestamp - candidate.stat().st_mtime <= self.stage_max_age_seconds:
                    continue
                candidate.unlink()
                deleted += 1
            except FileNotFoundError:
                continue
            except OSError:
                continue
        return deleted

    def _stage(self, key: str, content: bytes) -> str:
        self._ensure_stage_root()
        filename = f"{key}.pdf"
        destination = self.stage_root / filename
        temporary = self.stage_root / f".{key}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        temporary.write_bytes(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        return filename

    def _stage_path(self, filename: str) -> Path:
        if not FAX_STAGE_NAME.fullmatch(filename):
            raise FaxError("fax_staged_document_invalid")
        return self.stage_root / filename

    def propose(
        self,
        *,
        actor: Actor,
        idempotency_key: str,
        destination: str,
        filename: str,
        content: bytes,
    ) -> FaxSendProposal:
        self._ensure_enabled()
        self.cleanup_staged()
        prepared = prepare_fax_document(filename, content, max_bytes=self.fax.config.max_pdf_bytes)
        normalized_request = request_from_pdf(
            destination=destination,
            sender=f"governor:{actor.actor_id}",
            source_id=f"governor:{actor.scope}:{actor.actor_id}:{idempotency_key}",
            filename=prepared.filename,
            pdf=prepared.content,
            max_bytes=self.fax.config.max_pdf_bytes,
        )
        stage_key = hashlib.sha256(
            "\0".join(
                (
                    actor.scope,
                    actor.actor_id,
                    idempotency_key,
                    normalized_request.destination,
                    prepared.sha256,
                )
            ).encode("utf-8")
        ).hexdigest()
        staged_filename = self._stage(stage_key, prepared.content)
        pending = PendingFaxSend(
            destination=normalized_request.destination,
            sender=normalized_request.sender,
            source_id=normalized_request.source_id,
            filename=normalized_request.filename,
            sha256=prepared.sha256,
            size_bytes=prepared.size_bytes,
            page_count=prepared.page_count,
            staged_filename=staged_filename,
        )
        payload_kind, payload = pending_fax_record(pending)
        try:
            operation = self.operations.propose(
                OperationRequest(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    tool_name="fax.send",
                    operation_type="send",
                    parameters=fax_preview_payload(pending),
                    requires_confirmation=True,
                ),
                pending_kind=payload_kind,
                pending_payload=payload,
                confirmation_ttl=self.confirmation_ttl,
            )
        except Exception:
            self._stage_path(staged_filename).unlink(missing_ok=True)
            raise
        if not operation.created and operation.operation.status == "completed":
            self._stage_path(staged_filename).unlink(missing_ok=True)
        return FaxSendProposal(operation=operation, pending=pending)

    def approve(self, confirmation_id: str, *, actor: Actor) -> dict[str, object]:
        self._ensure_enabled()
        self.cleanup_staged()
        confirmation = self.operations.get_confirmation(confirmation_id)
        if confirmation is None:
            raise DurableGovernorError("confirmation_not_found")
        operation = self.operations.get_operation(confirmation.operation_id)
        if operation is None:
            raise DurableGovernorError("operation_not_found")
        if operation.tool_name != "fax.send" or operation.operation_type != "send":
            raise DurableGovernorError("confirmation_operation_mismatch")
        if confirmation.actor != actor:
            raise DurableGovernorError("confirmation_actor_mismatch")
        if confirmation.status == "approved" and operation.status == "completed":
            return {
                "operationId": operation.operation_id,
                "confirmationId": confirmation_id,
                "status": "completed",
                "replayed": True,
                "fax": dict(operation.result),
            }
        pending_record = self.operations.get_pending_payload(operation.operation_id)
        if pending_record is None:
            raise DurableGovernorError("operation_payload_not_found")
        pending = pending_fax_from_record(pending_record)
        if fax_preview_payload(pending) != dict(operation.parameters):
            raise DurableGovernorError("operation_payload_mismatch")
        staged = self._stage_path(pending.staged_filename)
        try:
            pdf = staged.read_bytes()
        except FileNotFoundError as exc:
            raise FaxError("fax_staged_document_missing") from exc
        if len(pdf) != pending.size_bytes or hashlib.sha256(pdf).hexdigest() != pending.sha256:
            raise FaxError("fax_staged_document_mismatch")
        request = request_from_pdf(
            destination=pending.destination,
            sender=pending.sender,
            source_id=pending.source_id,
            filename=pending.filename,
            pdf=pdf,
            max_bytes=self.fax.config.max_pdf_bytes,
        )
        if confirmation.status == "pending":
            self.operations.approve(confirmation_id, actor=actor)
        elif confirmation.status != "approved" or operation.status != "confirmed":
            raise DurableGovernorError("confirmation_not_pending")
        try:
            job, created = self.fax.submit(
                request,
                {
                    "source": "kaosgdd",
                    "actorId": actor.actor_id,
                    "scope": actor.scope,
                    "operationId": operation.operation_id,
                },
            )
            result = {
                "jobId": str(job.get("jobId") or ""),
                "status": str(job.get("status") or "queued"),
                "destination": pending.destination,
                "filename": pending.filename,
                "pageCount": pending.page_count,
                "created": created,
            }
            self.operations.complete(operation.operation_id, result=result)
            staged.unlink(missing_ok=True)
        except (FaxError, OSError, DurableGovernorError):
            # The connector may have accepted the stable job ID even if the
            # acknowledgement or operation completion failed. Keep the exact
            # staged PDF and confirmed operation so retrying this approval can
            # safely reconcile through FaxService idempotency.
            raise
        return {
            "operationId": operation.operation_id,
            "confirmationId": confirmation_id,
            "status": "completed",
            "replayed": False,
            "fax": result,
        }
