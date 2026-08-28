from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading
from typing import Any
import urllib.request


BIBLE_SOURCE_NAME = "Korean Bible 1910"
BIBLE_SOURCE_URL = "https://bible.helloao.org/api/kor_old/complete.simple.json"
BIBLE_LICENSE_URL = "https://ebible.org/Scriptures/details.php?id=kor"
QUOTE_SOURCE_NAME = "Quotable"
QUOTE_SOURCE_URL = "https://raw.githubusercontent.com/quotable-io/data/master/data/quotes.json"
QUOTE_LICENSE_URL = "https://github.com/quotable-io/data"
QUOTE_TAGS = frozenset(
    {
        "Courage",
        "Happiness",
        "Hope",
        "Inspirational",
        "Life",
        "Motivational",
        "Success",
        "Wisdom",
    }
)


class DailyContentError(RuntimeError):
    pass


@dataclass(frozen=True)
class BibleEntry:
    key: str
    reference: str
    text: str

    def render(self) -> str:
        return f"{self.reference} — {self.text}"


@dataclass(frozen=True)
class QuoteEntry:
    key: str
    text: str
    author: str


def render_quote(entry: QuoteEntry) -> str:
    attribution = f" — {entry.author}" if entry.author else ""
    return f"“{entry.text}”{attribution}"


def _clean_text(value: object, *, maximum: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > maximum:
        return ""
    return text


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _decode_json(response: Any) -> object:
    raw = response.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DailyContentError("daily_content_invalid_json") from exc


def _bible_entries(payload: object) -> list[BibleEntry]:
    if not isinstance(payload, Mapping):
        raise DailyContentError("daily_content_bible_invalid")
    entries: list[BibleEntry] = []
    for book in payload.get("books", []):
        if not isinstance(book, Mapping):
            continue
        book_id = _clean_text(book.get("id"), maximum=12)
        book_name = _clean_text(book.get("name"), maximum=32)
        if not book_id or not book_name:
            continue
        for chapter_item in book.get("chapters", []):
            if not isinstance(chapter_item, Mapping):
                continue
            chapter = chapter_item.get("chapter")
            if not isinstance(chapter, Mapping):
                continue
            chapter_number = chapter.get("number")
            if not isinstance(chapter_number, int) or chapter_number < 1:
                continue
            for item in chapter.get("content", []):
                if not isinstance(item, Mapping) or item.get("type") != "verse":
                    continue
                verse_number = item.get("number")
                text = _clean_text(item.get("text"))
                if not isinstance(verse_number, int) or verse_number < 1 or len(text) < 8:
                    continue
                entries.append(
                    BibleEntry(
                        key=f"{book_id}.{chapter_number}.{verse_number}",
                        reference=f"{book_name} {chapter_number}:{verse_number}",
                        text=text,
                    )
                )
    if len(entries) < 100:
        raise DailyContentError("daily_content_bible_too_small")
    return entries


def _quote_entries(payload: object) -> list[QuoteEntry]:
    if not isinstance(payload, list):
        raise DailyContentError("daily_content_quotes_invalid")
    entries: list[QuoteEntry] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        text = _clean_text(item.get("content"), maximum=180)
        author = _clean_text(item.get("author"), maximum=80)
        tags = {str(tag) for tag in item.get("tags", [])}
        key = _clean_text(item.get("_id"), maximum=80)
        normalized = text.casefold()
        if len(text) < 8 or not author or not key or not QUOTE_TAGS.intersection(tags) or normalized in seen:
            continue
        seen.add(normalized)
        entries.append(QuoteEntry(key=key, text=text, author=author))
    if len(entries) < 100:
        raise DailyContentError("daily_content_quotes_too_small")
    return entries


def _serialize_bible(entries: list[BibleEntry]) -> list[dict[str, str]]:
    return [{"key": item.key, "reference": item.reference, "text": item.text} for item in entries]


def _serialize_quotes(entries: list[QuoteEntry]) -> list[dict[str, str]]:
    return [{"key": item.key, "text": item.text, "author": item.author} for item in entries]


class DailyContentLibrary:
    def __init__(
        self,
        *,
        cache_path: Path,
        refresh_hours: int = 168,
        timeout_seconds: float = 30.0,
        bible_url: str = BIBLE_SOURCE_URL,
        quotes_url: str = QUOTE_SOURCE_URL,
        urlopen: Callable[..., Any] | None = None,
        fallback_bible: tuple[tuple[str, str], ...] = (),
        fallback_quotes: tuple[str, ...] = (),
    ) -> None:
        self.cache_path = cache_path
        self.refresh_hours = refresh_hours
        self.timeout_seconds = timeout_seconds
        self.bible_url = bible_url
        self.quotes_url = quotes_url
        self._urlopen = urlopen or urllib.request.urlopen
        self._fallback_bible = tuple(
            BibleEntry(f"fallback-bible-{index}", reference, text)
            for index, (reference, text) in enumerate(fallback_bible)
        )
        self._fallback_quotes = tuple(
            QuoteEntry(f"fallback-quote-{index}", text, "")
            for index, text in enumerate(fallback_quotes)
        )
        self._lock = threading.RLock()
        self._loaded = False
        self._bible: tuple[BibleEntry, ...] = ()
        self._quotes: tuple[QuoteEntry, ...] = ()
        self._refreshed_at = ""
        self.last_error = ""

    def _request_json(self, url: str) -> object:
        if not url.startswith("https://"):
            raise DailyContentError("daily_content_source_must_be_https")
        request = urllib.request.Request(url, headers={"User-Agent": "KaosGovernor/daily-content"})
        try:
            with self._urlopen(request, timeout=self.timeout_seconds) as response:
                return _decode_json(response)
        except DailyContentError:
            raise
        except Exception as exc:
            raise DailyContentError(f"daily_content_fetch_failed:{type(exc).__name__}") from exc

    def _load_cache(self) -> None:
        if self._loaded:
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, Mapping):
            bible = []
            for item in payload.get("bible", []):
                if isinstance(item, Mapping):
                    key = _clean_text(item.get("key"), maximum=80)
                    reference = _clean_text(item.get("reference"), maximum=80)
                    text = _clean_text(item.get("text"))
                    if key and reference and text:
                        bible.append(BibleEntry(key, reference, text))
            quotes = []
            for item in payload.get("quotes", []):
                if isinstance(item, Mapping):
                    key = _clean_text(item.get("key"), maximum=80)
                    text = _clean_text(item.get("text"), maximum=180)
                    author = _clean_text(item.get("author"), maximum=80)
                    if key and text and author:
                        quotes.append(QuoteEntry(key, text, author))
            self._bible = tuple(bible)
            self._quotes = tuple(quotes)
            self._refreshed_at = str(payload.get("refreshedAt") or "")
        self._loaded = True

    def _is_fresh(self, now: datetime) -> bool:
        if not self._bible or not self._quotes or not self._refreshed_at:
            return False
        try:
            refreshed = datetime.fromisoformat(self._refreshed_at)
        except ValueError:
            return False
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=now.tzinfo)
        return now - refreshed < timedelta(hours=self.refresh_hours)

    def refresh(self, *, force: bool = False, now: datetime | None = None) -> dict[str, object]:
        current = now or datetime.now().astimezone()
        with self._lock:
            self._load_cache()
            if not force and self._is_fresh(current):
                return self.status()
        try:
            bible = _bible_entries(self._request_json(self.bible_url))
            quotes = _quote_entries(self._request_json(self.quotes_url))
            refreshed_at = current.isoformat()
            payload: dict[str, object] = {
                "version": 1,
                "refreshedAt": refreshed_at,
                "bibleSource": {
                    "name": BIBLE_SOURCE_NAME,
                    "url": self.bible_url,
                    "license": BIBLE_LICENSE_URL,
                },
                "quoteSource": {
                    "name": QUOTE_SOURCE_NAME,
                    "url": self.quotes_url,
                    "license": QUOTE_LICENSE_URL,
                },
                "bible": _serialize_bible(bible),
                "quotes": _serialize_quotes(quotes),
            }
            _atomic_json(self.cache_path, payload)
            with self._lock:
                self._bible = tuple(bible)
                self._quotes = tuple(quotes)
                self._refreshed_at = refreshed_at
                self.last_error = ""
            return self.status()
        except Exception as exc:
            with self._lock:
                self.last_error = f"{type(exc).__name__}: {exc}"
            return self.status()

    def _available_bible(self) -> tuple[BibleEntry, ...]:
        with self._lock:
            self._load_cache()
            return self._bible or self._fallback_bible

    def _available_quotes(self) -> tuple[QuoteEntry, ...]:
        with self._lock:
            self._load_cache()
            return self._quotes or self._fallback_quotes

    def for_day(self, ordinal: int) -> tuple[BibleEntry, QuoteEntry]:
        bible = self._available_bible()
        quotes = self._available_quotes()
        if not bible or not quotes:
            raise DailyContentError("daily_content_unavailable")
        return bible[ordinal % len(bible)], quotes[ordinal % len(quotes)]

    def next_bible(self, current_line: str) -> BibleEntry:
        entries = self._available_bible()
        if not entries:
            raise DailyContentError("daily_content_bible_unavailable")
        index = next(
            (index for index, entry in enumerate(entries) if current_line.startswith(f"{entry.reference} —")),
            -1,
        )
        return entries[(index + 1) % len(entries)]

    def next_quote(self, current_line: str) -> QuoteEntry:
        entries = self._available_quotes()
        if not entries:
            raise DailyContentError("daily_content_quotes_unavailable")
        index = next(
            (index for index, entry in enumerate(entries) if entry.text in current_line),
            -1,
        )
        return entries[(index + 1) % len(entries)]

    def status(self) -> dict[str, object]:
        with self._lock:
            self._load_cache()
            return {
                "cachePath": str(self.cache_path),
                "bibleCount": len(self._bible) or len(self._fallback_bible),
                "quoteCount": len(self._quotes) or len(self._fallback_quotes),
                "webBibleCount": len(self._bible),
                "webQuoteCount": len(self._quotes),
                "refreshedAt": self._refreshed_at,
                "refreshHours": self.refresh_hours,
                "bibleSource": BIBLE_SOURCE_NAME,
                "quoteSource": QUOTE_SOURCE_NAME,
                "lastError": self.last_error,
            }
