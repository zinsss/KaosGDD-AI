from __future__ import annotations

import glob
import os
import re
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path


DEFAULT_TEXTBOOK_INDEX_PATH = Path("/data/textbooks/harrison/index/harrison22.index.sqlite")
DEFAULT_TEXTBOOK_INDEX_GLOB = "/data/textbooks/*/index/*.index.sqlite"
MAX_TEXTBOOK_EXCERPT_CHARS = int(os.environ.get("AI_TASK_TEXTBOOK_EXCERPT_CHARS", "1800") or "1800")


def textbook_index_path() -> Path:
    return Path(os.environ.get("AI_TASK_TEXTBOOK_INDEX_PATH", str(DEFAULT_TEXTBOOK_INDEX_PATH))).expanduser()


def textbook_index_paths(index_path: Path | None = None) -> list[Path]:
    if index_path is not None:
        return [index_path.expanduser()]
    configured = os.environ.get("AI_TASK_TEXTBOOK_INDEX_PATH", "").strip()
    if configured and Path(configured).expanduser() != DEFAULT_TEXTBOOK_INDEX_PATH:
        return [Path(configured).expanduser()]
    index_glob = os.environ.get("AI_TASK_TEXTBOOK_INDEX_GLOB", DEFAULT_TEXTBOOK_INDEX_GLOB).strip()
    paths = [Path(path) for path in glob.glob(index_glob)] if index_glob else []
    if DEFAULT_TEXTBOOK_INDEX_PATH.is_file() and DEFAULT_TEXTBOOK_INDEX_PATH not in paths:
        paths.append(DEFAULT_TEXTBOOK_INDEX_PATH)
    return sorted(path for path in paths if path.is_file())


def textbook_search_enabled() -> bool:
    value = os.environ.get("AI_TASK_TEXTBOOK_SEARCH_ENABLED", "").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(textbook_index_paths())


def search_textbook_sources(
    prompt: str,
    plan: Mapping[str, object] | None = None,
    *,
    limit: int = 3,
    index_path: Path | None = None,
) -> list[dict[str, object]]:
    paths = textbook_index_paths(index_path)
    if limit <= 0 or not paths:
        return []
    queries = _textbook_queries(prompt, plan)
    if not queries:
        return []
    ranking_context = " ".join([prompt, *queries]).casefold()
    candidates: list[dict[str, object]] = []
    seen_pages: set[tuple[str, int]] = set()
    for path in paths:
        metadata = _textbook_metadata(path)
        book_priority = _textbook_book_priority(path, ranking_context)
        try:
            conn = sqlite3.connect(path)
        except sqlite3.Error:
            continue
        try:
            for query_index, query in enumerate(queries):
                match = _fts_match_query(query)
                if not match:
                    continue
                try:
                    rows = conn.execute(
                        """
                        SELECT pages.page, pages.text, bm25(pages_fts) AS rank
                        FROM pages_fts
                        JOIN pages ON pages_fts.rowid = pages.id
                        WHERE pages_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (match, max(limit * 2, 6)),
                    ).fetchall()
                except sqlite3.Error:
                    continue
                for page, text, rank in rows:
                    page_number = int(page)
                    page_key = (str(path), page_number)
                    if page_key in seen_pages:
                        continue
                    excerpt = _textbook_excerpt(str(text or ""), query)
                    if not excerpt:
                        continue
                    seen_pages.add(page_key)
                    candidates.append(
                        {
                            "title": f"{metadata['title']} p. {page_number}",
                            "book": metadata["book"],
                            "edition": metadata["edition"],
                            "source": path.name,
                            "page": page_number,
                            "citation": f"{metadata['citationLabel']}, p. {page_number}",
                            "excerpt": excerpt,
                            "_rank": float(rank or 0),
                            "_queryIndex": query_index,
                            "_bookPriority": book_priority,
                        }
                    )
        finally:
            conn.close()
    results: list[dict[str, object]] = []
    for item in sorted(candidates, key=lambda value: (value["_queryIndex"], value["_bookPriority"], value["_rank"], str(value["citation"]))):
        results.append({key: value for key, value in item.items() if not key.startswith("_")})
        if len(results) >= limit:
            return results
    return results


def _textbook_book_priority(path: Path, query_context: str) -> int:
    psychiatry_terms = {
        "schizophrenia",
        "psychosis",
        "bipolar",
        "depressive disorder",
        "major depression",
        "panic disorder",
        "anxiety disorder",
        "obsessive compulsive",
        "posttraumatic stress",
        "attention deficit",
        "autism spectrum",
        "eating disorder",
        "substance use disorder",
        "조현병",
        "정신증",
        "양극성",
        "조울증",
        "우울증",
        "공황",
        "불안장애",
        "강박",
        "외상후",
        "주의력결핍",
        "자폐",
        "섭식장애",
        "물질사용",
    }
    if any(term in query_context for term in psychiatry_terms):
        return 0 if "kaplan" in path.name.casefold() else 1
    return 0


def _textbook_metadata(path: Path) -> dict[str, str]:
    defaults = {
        "book": "Harrison's Principles of Internal Medicine",
        "edition": "22e",
        "citationLabel": "Harrison 22e",
    }
    if "kaplan" in path.name.casefold():
        defaults = {
            "book": "Kaplan & Sadock's Synopsis of Psychiatry",
            "edition": "12e",
            "citationLabel": "Kaplan & Sadock Synopsis 12e",
        }
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        conn = None
    if conn is not None:
        try:
            rows = conn.execute("SELECT key, value FROM metadata").fetchall()
            for key, value in rows:
                normalized_key = str(key)
                if normalized_key in defaults and str(value or "").strip():
                    defaults[normalized_key] = " ".join(str(value).split())[:160]
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    manifest_path = path.with_name(path.name.replace(".index.sqlite", ".index_manifest.json"))
    if manifest_path.is_file():
        try:
            import json

            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key in ("book", "edition", "citationLabel"):
                value = payload.get(key) if isinstance(payload, dict) else ""
                if str(value or "").strip():
                    defaults[key] = " ".join(str(value).split())[:160]
        except (OSError, ValueError):
            pass
    return {
        "book": defaults["book"],
        "edition": defaults["edition"],
        "citationLabel": defaults["citationLabel"],
        "title": f"{defaults['book']}, {defaults['edition']}",
    }


def _textbook_queries(prompt: str, plan: Mapping[str, object] | None = None) -> list[str]:
    values: list[str] = []
    values.append(prompt)
    if isinstance(plan, Mapping):
        values.append(str(plan.get("query") or ""))
        alternates = plan.get("alternateQueries")
        if isinstance(alternates, Iterable) and not isinstance(alternates, (str, bytes)):
            values.extend(str(item or "") for item in alternates)
    expanded = []
    joined = " ".join(values).casefold()
    aliases = {
        "하지불안증후군": ("restless legs syndrome", "restless legs"),
        "rls": ("restless legs syndrome",),
        "이석증": ("benign paroxysmal positional vertigo", "BPPV"),
        "양성돌발체위현훈": ("benign paroxysmal positional vertigo", "BPPV"),
        "양성돌발성체위현훈": ("benign paroxysmal positional vertigo", "BPPV"),
        "당뇨": ("diabetes mellitus", "diabetes"),
        "고혈압": ("hypertension",),
        "심부전": ("heart failure",),
        "폐렴": ("pneumonia",),
        "천식": ("asthma",),
        "copd": ("chronic obstructive pulmonary disease",),
        "조현병": ("schizophrenia", "psychosis"),
        "정신증": ("psychosis",),
        "양극성": ("bipolar disorder",),
        "조울증": ("bipolar disorder",),
        "우울증": ("depressive disorder", "major depression", "depression"),
        "공황": ("panic disorder",),
        "불안장애": ("anxiety disorder",),
        "강박": ("obsessive compulsive disorder", "OCD"),
        "외상후": ("posttraumatic stress disorder", "PTSD"),
        "ptsd": ("posttraumatic stress disorder",),
        "주의력결핍": ("attention deficit hyperactivity disorder", "ADHD"),
        "adhd": ("attention deficit hyperactivity disorder",),
        "자폐": ("autism spectrum disorder",),
        "섭식장애": ("eating disorder",),
        "알코올": ("alcohol use disorder",),
        "물질사용": ("substance use disorder",),
    }
    for value in values:
        query = " ".join(str(value or "").split())
        if query:
            expanded.append(query)
    for needle, replacements in aliases.items():
        if needle in joined:
            expanded.extend(replacements)
    return _unique(expanded)[:8]


def _fts_match_query(query: str) -> str:
    raw = " ".join(str(query or "").split())
    if not raw:
        return ""
    if re.search(r"[A-Za-z]", raw):
        words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", raw)
        meaningful = [word for word in words if len(word) > 2]
        if not meaningful:
            return ""
        phrases = []
        if len(meaningful) >= 2:
            phrases.append(" ".join(meaningful[:6]))
        phrases.extend(meaningful[:6])
        return " OR ".join(f'"{_fts_quote(item)}"' for item in _unique(phrases))
    korean = re.findall(r"[가-힣]{2,}", raw)
    return " OR ".join(f'"{_fts_quote(item)}"' for item in _unique(korean[:6]))


def _textbook_excerpt(text: str, query: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return ""
    lower = collapsed.casefold()
    terms = [term.casefold() for term in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}|[가-힣]{2,}", query)]
    start = 0
    hits = [lower.find(term) for term in terms if lower.find(term) >= 0]
    if hits:
        start = max(0, min(hits) - 300)
    excerpt = collapsed[start : start + MAX_TEXTBOOK_EXCERPT_CHARS].strip()
    if start > 0:
        excerpt = "…" + excerpt
    if start + MAX_TEXTBOOK_EXCERPT_CHARS < len(collapsed):
        excerpt += "…"
    return excerpt


def _unique(values: Iterable[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = " ".join(str(value or "").split()).strip()
        key = item.casefold()
        if item and key not in seen:
            selected.append(item[:200])
            seen.add(key)
    return selected


def _fts_quote(value: str) -> str:
    return str(value or "").replace('"', '""')
