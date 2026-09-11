"""Document intake adapters for KaosGovernor."""

from .intake import DocumentInboxRecord, DocumentIntakeStore
from .paperless import (
    DocumentIntakeError,
    PaperlessConfig,
    PaperlessDocument,
    PaperlessDocumentService,
    PaperlessResult,
    PaperlessSearchPage,
    PaperlessSearchResult,
    PaperlessTag,
    PaperlessTask,
)
from .submission import submit_pdf_to_inbox

__all__ = (
    "DocumentIntakeError",
    "DocumentInboxRecord",
    "DocumentIntakeStore",
    "PaperlessConfig",
    "PaperlessDocument",
    "PaperlessDocumentService",
    "PaperlessResult",
    "PaperlessSearchPage",
    "PaperlessSearchResult",
    "PaperlessTag",
    "PaperlessTask",
    "submit_pdf_to_inbox",
)
