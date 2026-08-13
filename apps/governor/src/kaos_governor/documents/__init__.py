"""Document intake adapters for KaosGovernor."""

from .paperless import (
    DocumentIntakeError,
    PaperlessConfig,
    PaperlessDocumentService,
    PaperlessResult,
    PaperlessSearchPage,
    PaperlessSearchResult,
)

__all__ = (
    "DocumentIntakeError",
    "PaperlessConfig",
    "PaperlessDocumentService",
    "PaperlessResult",
    "PaperlessSearchPage",
    "PaperlessSearchResult",
)
