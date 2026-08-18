"""Document intake adapters for KaosGovernor."""

from .paperless import (
    DocumentIntakeError,
    PaperlessConfig,
    PaperlessDocument,
    PaperlessDocumentService,
    PaperlessResult,
    PaperlessSearchPage,
    PaperlessSearchResult,
    PaperlessTag,
)

__all__ = (
    "DocumentIntakeError",
    "PaperlessConfig",
    "PaperlessDocument",
    "PaperlessDocumentService",
    "PaperlessResult",
    "PaperlessSearchPage",
    "PaperlessSearchResult",
    "PaperlessTag",
)
