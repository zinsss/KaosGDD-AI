from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Route(StrEnum):
    CHAT = "chat"
    DEEP = "deep"


@dataclass(frozen=True)
class BrainRequest:
    route: Route
    text: str


DEEP_PREFIXES = ("deep:", "think:", "깊게:", "생각:")


def parse_request(content: str) -> BrainRequest | None:
    text = content.strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in DEEP_PREFIXES:
        if lowered.startswith(prefix):
            remaining = text[len(prefix) :].strip()
            if not remaining:
                return None
            return BrainRequest(Route.DEEP, remaining)
    return BrainRequest(Route.CHAT, text)
