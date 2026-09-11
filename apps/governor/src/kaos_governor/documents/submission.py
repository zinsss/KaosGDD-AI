from __future__ import annotations

import hashlib

from .intake import DocumentIntakeStore
from .paperless import DocumentIntakeError, PaperlessDocumentService


def submit_pdf_to_inbox(
    *,
    filename: str,
    content: bytes,
    title: str,
    source: str,
    service: PaperlessDocumentService,
    store: DocumentIntakeStore,
) -> dict[str, object]:
    if not filename or not content or not str(filename).lower().endswith(".pdf"):
        raise DocumentIntakeError("pdf_attachment_required")

    existing = store.find_active_by_sha(hashlib.sha256(content).hexdigest())
    if existing:
        return {"ok": True, "duplicate": True, "item": existing.as_dict()}

    result = service.submit_pdf(filename, content, title=title, source=source)
    record = store.add_submitted(
        title=title or result.filename,
        filename=result.filename,
        content=content,
        task_id=result.task_id,
        source=source,
    )
    return {
        "ok": True,
        "duplicate": False,
        "item": record.as_dict(),
        "paperless": result.as_dict(),
    }
