"""Read-only Memos backend adapter for KaosGovernor."""

from .service import (
    Memo,
    MemoSearchPage,
    MemoSearchResult,
    MemosConfig,
    MemosConfigurationError,
    MemosError,
    MemosService,
)

__all__ = (
    "Memo",
    "MemoSearchPage",
    "MemoSearchResult",
    "MemosConfig",
    "MemosConfigurationError",
    "MemosError",
    "MemosService",
)
