from __future__ import annotations


def normalize_dotdot_query(query: object) -> str:
    return " ".join(str(query or "").split())
