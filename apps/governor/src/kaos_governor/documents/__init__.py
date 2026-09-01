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
)
