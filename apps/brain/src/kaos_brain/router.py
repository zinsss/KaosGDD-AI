from __future__ import annotations

from enum import StrEnum


class RouteDecision(StrEnum):
    ANSWER = "answer"
    DEEP = "deep"


def parse_route_decision(raw: str) -> RouteDecision:
    normalized = raw.strip().lower()
    if normalized.startswith("deep"):
        return RouteDecision.DEEP
    return RouteDecision.ANSWER
