from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class PageWindow[T]:
    items: list[T]
    page: int
    page_size: int
    total: int
    max_page: int

    @property
    def start_number(self) -> int:
        return self.page * self.page_size + 1 if self.items else 0

    @property
    def range_label(self) -> str:
        return range_summary(self.start_number, len(self.items), self.total)

    @property
    def page_label(self) -> str:
        return page_status_label(self.page + 1, self.max_page + 1)


def page_window(items: Sequence[T], *, page: int, page_size: int) -> PageWindow[T]:
    normalized_size = max(1, page_size)
    total = len(items)
    max_page = 0 if total <= 0 else (total - 1) // normalized_size
    normalized_page = min(max(0, page), max_page)
    start = normalized_page * normalized_size
    return PageWindow(
        items=list(items[start : start + normalized_size]),
        page=normalized_page,
        page_size=normalized_size,
        total=total,
        max_page=max_page,
    )


def range_summary(start: int, count: int, total: int) -> str:
    if count <= 0 or total <= 0:
        return "<0 of 0>"
    return f"<{start}-{start + count - 1} of {total}>"


def page_status_label(page: int, page_total: int) -> str:
    return f"Page {max(1, page)}/{max(1, page_total)}"
