"""Read-only Memos backend adapter for KaosGovernor."""

from .service import (
    Memo,
    MemoSearchResult,
    MemosConfig,
    MemosConfigurationError,
    MemosError,
    MemosService,
)

__all__ = (
    "Memo",
    "MemoSearchResult",
    "MemosConfig",
    "MemosConfigurationError",
    "MemosError",
    "MemosService",
)
