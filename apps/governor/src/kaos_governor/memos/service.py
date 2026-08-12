from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


MEMO_NAME = re.compile(r"^memos/[A-Za-z0-9_-]+$")
CREATOR_NAME = re.compile(r"^users/[A-Za-z0-9._-]+$")
MAX_QUERY_CHARACTERS = 300
MAX_TAGS = 10
MAX_TAG_CHARACTERS = 64


class MemosConfigurationError(ValueError):
    """Raised when the Memos adapter configuration is invalid."""


class MemosError(RuntimeError):
    """Raised with a stable code that is safe to return to a tool caller."""

    def __init__(self, code: str, *, upstream_status: int = 0) -> None:
        super().__init__(code)
        self.code = code
        self.upstream_status = upstream_status


def _boolean(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise MemosConfigurationError(f"{name} must be true or false")


def _positive_int(env: Mapping[str, str], name: str, default: int, maximum: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise MemosConfigurationError(f"{name} must be an integer") from exc
    if value <= 0 or value > maximum:
        raise MemosConfigurationError(f"{name} must be between 1 and {maximum}")
    return value


def _secret(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise MemosConfigurationError(f"set either {name} or {name}_FILE, not both")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MemosConfigurationError(f"unable to read {name}_FILE") from exc


@dataclass(frozen=True)
class MemosConfig:
    enabled: bool
    base_url: str
    access_token: str
    creator: str
    timeout_seconds: int
    max_results: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "MemosConfig":
        source = os.environ if env is None else env
        enabled = _boolean(source, "MEMOS_SEARCH_ENABLED")
        base_url = source.get("MEMOS_BASE_URL", "").strip().rstrip("/")
        access_token = _secret(source, "MEMOS_ACCESS_TOKEN")
        creator = source.get("MEMOS_CREATOR", "").strip()
        timeout_seconds = _positive_int(source, "MEMOS_TIMEOUT_SECONDS", 15, 120)
        max_results = _positive_int(source, "MEMOS_SEARCH_MAX_RESULTS", 20, 100)

        if enabled:
            parsed = urllib.parse.urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise MemosConfigurationError("MEMOS_BASE_URL must be an absolute HTTP(S) URL")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise MemosConfigurationError("MEMOS_BASE_URL must not contain credentials, a query, or a fragment")
            if not access_token:
                raise MemosConfigurationError("MEMOS_ACCESS_TOKEN is required when Memos search is enabled")
            if not CREATOR_NAME.fullmatch(creator):
                raise MemosConfigurationError("MEMOS_CREATOR must use the users/<username> form")

        return cls(enabled, base_url, access_token, creator, timeout_seconds, max_results)


@dataclass(frozen=True)
class Memo:
    name: str
    content: str
    tags: tuple[str, ...]
    create_time: str
    update_time: str
    visibility: str
    pinned: bool

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "Memo":
        name = str(payload.get("name") or "")
        if not MEMO_NAME.fullmatch(name):
            raise MemosError("memos_upstream_response_invalid")
        raw_tags = payload.get("tags")
        tags = tuple(str(tag) for tag in raw_tags if str(tag).strip()) if isinstance(raw_tags, list) else ()
        return cls(
            name=name,
            content=str(payload.get("content") or ""),
            tags=tags,
            create_time=str(payload.get("createTime") or ""),
            update_time=str(payload.get("updateTime") or ""),
            visibility=str(payload.get("visibility") or ""),
            pinned=bool(payload.get("pinned", False)),
        )

    def as_dict(self, *, include_content: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "name": self.name,
            "tags": list(self.tags),
            "createTime": self.create_time,
            "updateTime": self.update_time,
            "visibility": self.visibility,
            "pinned": self.pinned,
        }
        if include_content:
            value["content"] = self.content
        return value


@dataclass(frozen=True)
class MemoSearchResult:
    memo: Memo
    snippet: str

    def as_dict(self) -> dict[str, object]:
        return {**self.memo.as_dict(include_content=False), "snippet": self.snippet}


def _normalize_query(value: object) -> str:
    query = " ".join(str(value or "").split())
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError("memos_query_too_long")
    return query


def _normalize_tags(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise ValueError("memos_tags_must_be_a_list")
    if len(values) > MAX_TAGS:
        raise ValueError("memos_too_many_tags")
    tags: list[str] = []
    for raw in values:
        tag = str(raw or "").strip().removeprefix("#")
        if not tag or len(tag) > MAX_TAG_CHARACTERS or any(character.isspace() for character in tag):
            raise ValueError("memos_tag_invalid")
        if tag not in tags:
            tags.append(tag)
    return tuple(tags)


def _snippet(content: str, query: str, length: int = 360) -> str:
    compact = " ".join(content.split())
    if len(compact) <= length:
        return compact
    index = compact.casefold().find(query.casefold()) if query else 0
    if index < 0:
        index = 0
    start = max(0, index - length // 3)
    end = min(len(compact), start + length)
    if end - start < length:
        start = max(0, end - length)
    return f"{'...' if start else ''}{compact[start:end].strip()}{'...' if end < len(compact) else ''}"


class MemosService:
    def __init__(
        self,
        config: MemosConfig,
        open_url: Callable[..., object] = urllib.request.urlopen,
    ) -> None:
        self.config = config
        self._open_url = open_url
        self._lock = threading.RLock()
        self._last_search_at = ""
        self._last_error = ""
        self._last_result_count = 0

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": self.config.enabled,
                "configured": bool(
                    self.config.enabled
                    and self.config.base_url
                    and self.config.access_token
                    and self.config.creator
                ),
                "creator": self.config.creator if self.config.enabled else "",
                "lastSearchAt": self._last_search_at,
                "lastResultCount": self._last_result_count,
                "lastError": self._last_error,
                "mode": "live-upstream",
            }

    def search(self, query: object = "", tags: object = None, limit: object = None) -> list[MemoSearchResult]:
        self._require_enabled()
        normalized_query = _normalize_query(query)
        normalized_tags = _normalize_tags(tags)
        if not normalized_query and not normalized_tags:
            raise ValueError("memos_query_or_tag_required")
        result_limit = self.config.max_results if limit is None else self._limit(limit)

        filters = [f"creator == {json.dumps(self.config.creator, ensure_ascii=False)}"]
        if normalized_query:
            filters.append(f"content.contains({json.dumps(normalized_query, ensure_ascii=False)})")
        if normalized_tags:
            encoded_tags = ", ".join(json.dumps(tag, ensure_ascii=False) for tag in normalized_tags)
            filters.append(f"tag in [{encoded_tags}]")
        query_string = urllib.parse.urlencode(
            {
                "pageSize": str(result_limit),
                "orderBy": "pinned desc, create_time desc",
                "filter": " && ".join(filters),
            }
        )
        try:
            payload = self._request(f"/api/v1/memos?{query_string}")
            raw_memos = payload.get("memos")
            if not isinstance(raw_memos, list):
                raise MemosError("memos_upstream_response_invalid")
            results = [
                MemoSearchResult(memo, _snippet(memo.content, normalized_query))
                for memo in (Memo.from_payload(item) for item in raw_memos if isinstance(item, dict))
            ][:result_limit]
        except Exception as exc:
            self._record_error(exc)
            raise
        with self._lock:
            self._last_search_at = _now()
            self._last_result_count = len(results)
            self._last_error = ""
        return results

    def get(self, name: object) -> Memo:
        self._require_enabled()
        normalized_name = str(name or "").strip()
        if not MEMO_NAME.fullmatch(normalized_name):
            raise ValueError("memos_name_invalid")
        memo_id = urllib.parse.quote(normalized_name.removeprefix("memos/"), safe="")
        try:
            return Memo.from_payload(self._request(f"/api/v1/memos/{memo_id}"))
        except Exception as exc:
            self._record_error(exc)
            raise

    def _limit(self, value: object) -> int:
        if isinstance(value, bool):
            raise ValueError("memos_limit_invalid")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("memos_limit_invalid") from exc
        if parsed <= 0 or parsed > self.config.max_results:
            raise ValueError("memos_limit_invalid")
        return parsed

    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise MemosError("memos_search_disabled")

    def _request(self, path: str) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.config.base_url}{path}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.config.access_token}",
                "User-Agent": "KaosGovernor-Memos/0.1",
            },
        )
        try:
            with self._open_url(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise MemosError("memos_not_found", upstream_status=404) from exc
            if exc.code in {401, 403}:
                raise MemosError("memos_upstream_auth_failed", upstream_status=exc.code) from exc
            raise MemosError("memos_upstream_error", upstream_status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MemosError("memos_upstream_unavailable") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MemosError("memos_upstream_response_invalid") from exc
        if not isinstance(payload, dict):
            raise MemosError("memos_upstream_response_invalid")
        return payload

    def _record_error(self, error: Exception) -> None:
        with self._lock:
            self._last_error = error.code if isinstance(error, MemosError) else type(error).__name__


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
