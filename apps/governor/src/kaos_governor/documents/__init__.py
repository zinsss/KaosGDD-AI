"""Document intake adapters for KaosGovernor."""

from .paperless import (
    DocumentIntakeError,
    PaperlessConfig,
    PaperlessDocumentService,
    PaperlessResult,
    PaperlessSearchResult,
)

__all__ = (
    "DocumentIntakeError",
    "PaperlessConfig",
    "PaperlessDocumentService",
    "PaperlessResult",
    "PaperlessSearchResult",
)
