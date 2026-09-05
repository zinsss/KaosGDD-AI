from __future__ import annotations

import io
import html
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import uuid
import hashlib
import threading
import ipaddress
import zipfile
from html.parser import HTMLParser

from kaos_governor import ledger
from kaos_governor.ai_tasks import AITaskArchive, AITaskError
from kaos_governor.calendar import GeneratedCalendarSettings
from kaos_governor.database import connect, database_status, wait_for_database_and_migrate
from kaos_governor.documents import (
    DocumentIntakeStore,
    DocumentIntakeError,
    PaperlessConfig,
    PaperlessDocumentService,
)
from kaos_governor.fax import FaxConfig, FaxError, FaxService
from kaos_governor.mail import MailOrganizerConfig, MailOrganizerError, NaverMailOrganizer
from kaos_governor.mail.naver import KST, NaverMailConfig, NaverMailError, NaverMailPoller
from kaos_governor.memos import relay as memos_relay
from kaos_governor.official_search import (
    allowed_official_health_hosts,
    is_allowed_official_health_host,
    looks_like_treatment_options_query,
    official_health_search_candidates,
)
from kaos_governor.tasks import PostgresRecurringTaskStore, RecurringTaskDefinition, RecurringTaskError, RecurringTaskService, validate_payload
from kaos_governor.textbook_search import search_textbook_sources
from kaos_governor.system_updates import SystemUpdatesError, read_system_updates


PORT = int(os.environ.get("GOVERNOR_API_PORT", "8096"))
MIGRATIONS = Path(os.environ.get("GOVERNOR_MIGRATIONS_DIR", "/usr/local/share/kaos-governor/migrations"))
MAX_REQUEST_BYTES = 500_000
MAX_MULTIPART_OVERHEAD_BYTES = 256_000
CALENDAR_ADAPTER_INTERNAL_URL = os.environ.get("CALENDAR_ADAPTER_INTERNAL_URL", "http://calendar-adapter:8091").rstrip("/")
CALENDAR_ADAPTER_TIMEOUT_SECONDS = float(os.environ.get("CALENDAR_ADAPTER_TIMEOUT_SECONDS", "20"))
SYSTEM_STATUS_TOOLS_BASE_URL = os.environ.get("SYSTEM_STATUS_TOOLS_BASE_URL", "http://governor-discord:8098").rstrip("/")
SYSTEM_STATUS_TIMEOUT_SECONDS = float(os.environ.get("SYSTEM_STATUS_TIMEOUT_SECONDS", "5"))
DOCUMENT_TAG_AI_URL = os.environ.get("DOCUMENT_TAG_AI_URL", "").strip()
DOCUMENT_TAG_AI_TOKEN = os.environ.get("DOCUMENT_TAG_AI_TOKEN", "").strip()
DOCUMENT_TAG_AI_TOKEN_FILE = os.environ.get("DOCUMENT_TAG_AI_TOKEN_FILE", "").strip()
DOCUMENT_TAG_AI_TIMEOUT_SECONDS = float(os.environ.get("DOCUMENT_TAG_AI_TIMEOUT_SECONDS", "20") or "20")
AI_TASKS_BRAIN_URL = os.environ.get("AI_TASKS_BRAIN_URL", "").strip()
AI_TASKS_WEB_BRAIN_URL = os.environ.get("AI_TASKS_WEB_BRAIN_URL", "").strip()
AI_TASKS_BRAIN_TOKEN = os.environ.get("AI_TASKS_BRAIN_TOKEN", "").strip()
AI_TASKS_BRAIN_TOKEN_FILE = os.environ.get("AI_TASKS_BRAIN_TOKEN_FILE", "").strip()
AI_TASKS_BRAIN_TIMEOUT_SECONDS = float(os.environ.get("AI_TASKS_BRAIN_TIMEOUT_SECONDS", "60") or "60")
OFFICIAL_MEMO_FETCH_TIMEOUT_SECONDS = float(os.environ.get("OFFICIAL_MEMO_FETCH_TIMEOUT_SECONDS", "15") or "15")
OFFICIAL_MEMO_MAX_SOURCE_CHARS = int(os.environ.get("OFFICIAL_MEMO_MAX_SOURCE_CHARS", "20000") or "20000")
OFFICIAL_MEMO_MAX_PDF_BYTES = int(os.environ.get("OFFICIAL_MEMO_MAX_PDF_MB", "20") or "20") * 1024 * 1024
OFFICIAL_MEMO_MAX_ATTACHMENT_BYTES = int(os.environ.get("OFFICIAL_MEMO_MAX_ATTACHMENT_MB", "20") or "20") * 1024 * 1024
OFFICIAL_MEMO_MAX_ATTACHMENT_CHARS = int(os.environ.get("OFFICIAL_MEMO_MAX_ATTACHMENT_CHARS", "12000") or "12000")
OFFICIAL_MEMO_MAX_ATTACHMENTS = int(os.environ.get("OFFICIAL_MEMO_MAX_ATTACHMENTS", "2") or "2")
WEATHER_LOCATIONS = {
    "pohang": "포항",
    "daegu": "대구",
    "yeongcheon": "영천",
    "yeonghae": "영해",
}


class SystemStatusError(RuntimeError):
    def __init__(self, code: str, status: int = 503) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def xlsx_response(handler: BaseHTTPRequestHandler, data: bytes, filename: str) -> None:
    encoded_name = urllib.parse.quote(filename, safe="")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    handler.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def bytes_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    content_type: str,
    data: bytes,
    *,
    private: bool = False,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "private, no-store" if private else "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def inline_pdf_response(handler: BaseHTTPRequestHandler, data: bytes, filename: str) -> None:
    encoded_name = urllib.parse.quote(filename, safe="")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/pdf")
    handler.send_header("Content-Disposition", f"inline; filename*=UTF-8''{encoded_name}")
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def inline_file_response(handler: BaseHTTPRequestHandler, data: bytes, filename: str, content_type: str) -> None:
    encoded_name = urllib.parse.quote(filename or "attachment", safe="")
    safe_content_type = re.sub(r"[\r\n;]+", "", content_type or "").strip() or "application/octet-stream"
    handler.send_response(200)
    handler.send_header("Content-Type", safe_content_type)
    handler.send_header("Content-Disposition", f"inline; filename*=UTF-8''{encoded_name}")
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def profile_from_headers(headers) -> str:
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(":", 1)[0].lower()
    return "family" if host == "family.kaosgdd.net" else "main"


def require_family_profile(headers) -> None:
    if profile_from_headers(headers) != "family":
        raise ValueError("family_profile_required")


def require_main_access(headers) -> str:
    profile, email = memos_relay.verify_cloudflare_access(headers)
    if profile != "personal":
        raise ValueError("main_profile_required")
    return email


def require_ai_task_access(headers) -> str:
    profile, email = memos_relay.verify_cloudflare_access(headers)
    if profile not in {"personal", "family"}:
        raise ValueError("ai_task_profile_required")
    return email


def request_actor(headers) -> str:
    return ledger.actor_name(
        headers.get("Cf-Access-Authenticated-User-Email")
        or headers.get("X-Forwarded-Email")
        or "family"
    )


def secret_value(name: str, *, default_file: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    path = os.environ.get(f"{name}_FILE", "").strip() or default_file
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def discord_brain_channel_url() -> str:
    configured = os.environ.get("DISCORD_BRAIN_CHANNEL_URL", "").strip()
    if configured.startswith(("https://discord.com/channels/", "discord://")):
        return configured
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    channel_id = os.environ.get("DISCORD_BRAIN_CHANNEL_ID", "").strip()
    if guild_id.isdigit() and channel_id.isdigit():
        return f"https://discord.com/channels/{guild_id}/{channel_id}"
    return ""


def system_status_payload(profile: str, urlopen=urllib.request.urlopen) -> dict[str, object]:
    if profile != "main":
        raise SystemStatusError("main_profile_required", 404)
    token = secret_value("GOVERNOR_API_TOKEN", default_file="/run/secrets/governor_api_token")
    if not token:
        raise SystemStatusError("system_status_token_missing", 503)
    query = urllib.parse.urlencode({"profile": "main"})
    request = urllib.request.Request(
        f"{SYSTEM_STATUS_TOOLS_BASE_URL}/tools/system/status?{query}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urlopen(request, timeout=SYSTEM_STATUS_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            code = str(payload.get("error") or f"system_status_http_{exc.code}")
        except Exception:
            code = f"system_status_http_{exc.code}"
        raise SystemStatusError(code, 502) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SystemStatusError("system_status_unreachable", 503) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemStatusError("system_status_invalid_json", 502) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), dict):
        raise SystemStatusError("system_status_invalid_payload", 502)
    return {
        "ok": True,
        "profile": "main",
        "updatedAt": _utc_now_iso(),
        "source": str(payload.get("source") or "governor-runtime-health"),
        "date": str(payload.get("date") or ""),
        "status": dict(payload["status"]),
        "brainChannelUrl": discord_brain_channel_url(),
        "readOnly": True,
    }


def system_updates_payload(profile: str) -> dict[str, object]:
    if profile != "main":
        raise SystemUpdatesError("main_profile_required")
    return {
        "ok": True,
        "profile": "main",
        "updatedAt": _utc_now_iso(),
        "readOnly": True,
        "status": read_system_updates(),
    }


def supply_status_for_error(exc: Exception) -> int:
    if isinstance(exc, memos_relay.MemosRelayError):
        return exc.status
    code = str(exc)
    if code in {"main_profile_required", "supply_not_found"}:
        return 404
    if code in {"supply_title_required", "supply_mode_invalid", "supply_uid_required"}:
        return 400
    return 503


def _supply_title(value: object) -> str:
    title = " ".join(str(value or "").split())
    if not title:
        raise ValueError("supply_title_required")
    return title[:300]


def _supply_mode(query_string: str) -> str:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    mode = (params.get("mode") or ["active"])[0].strip().lower()
    if mode not in {"active", "done"}:
        raise ValueError("supply_mode_invalid")
    return mode


def _supply_item(task: dict[str, object]) -> dict[str, object]:
    status = str(task.get("status") or "NEEDS-ACTION").strip().upper()
    completed = str(task.get("completed") or "")
    last_modified = str(task.get("lastModified") or "")
    created = str(task.get("created") or "")
    return {
        "id": str(task.get("uid") or ""),
        "uid": str(task.get("uid") or ""),
        "collectionId": str(task.get("collection") or ""),
        "title": str(task.get("summary") or "Untitled supply"),
        "memo": str(task.get("description") or ""),
        "status": status,
        "done": status == "COMPLETED",
        "created": created,
        "lastModified": last_modified,
        "completed": completed,
        "updatedAt": completed or last_modified or created,
    }


def _supply_items(client: CalendarAdapterClient | None = None) -> list[dict[str, object]]:
    active_client = client or CalendarAdapterClient()
    items = [_supply_item(task) for task in active_client.list_tasks("supplies")]
    return [item for item in items if item["id"]]


def supplies_payload(query_string: str, client: CalendarAdapterClient | None = None) -> dict[str, object]:
    mode = _supply_mode(query_string)
    items = [item for item in _supply_items(client) if bool(item["done"]) == (mode == "done")]
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return {"ok": True, "mode": mode, "items": items}


def supply_presets_payload(client: CalendarAdapterClient | None = None) -> dict[str, object]:
    seen: set[str] = set()
    presets: list[dict[str, object]] = []
    for item in sorted(_supply_items(client), key=lambda row: str(row.get("updatedAt") or ""), reverse=True):
        title = str(item.get("title") or "").strip()
        key = title.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        presets.append({"name": title})
        if len(presets) >= 12:
            break
    return {"ok": True, "items": presets}


def create_supply_payload(payload: dict[str, object], client: CalendarAdapterClient | None = None) -> dict[str, object]:
    active_client = client or CalendarAdapterClient()
    title = _supply_title(payload.get("title") or payload.get("name"))
    collection_id = active_client.vtodo_collection_id("supplies", str(payload.get("collectionId") or ""))
    result = active_client.create_task(
        "supplies",
        {
            "collectionId": collection_id,
            "title": title,
            "memo": str(payload.get("memo") or "").strip(),
            "dueDate": "",
            "dueTime": "",
            "priority": "",
            "status": "NEEDS-ACTION",
        },
    )
    return {"ok": True, "item": {"id": str(result.get("uid") or ""), "uid": str(result.get("uid") or ""), "collectionId": str(result.get("collection") or collection_id), "title": title}}


def _find_supply(uid: str, client: CalendarAdapterClient | None = None) -> dict[str, object]:
    normalized = str(uid or "").strip()
    if not normalized:
        raise ValueError("supply_uid_required")
    for item in _supply_items(client):
        if item["id"] == normalized:
            return item
    raise ValueError("supply_not_found")


def set_supply_state_payload(uid: str, mode: str, client: CalendarAdapterClient | None = None) -> dict[str, object]:
    if mode not in {"active", "done"}:
        raise ValueError("supply_mode_invalid")
    active_client = client or CalendarAdapterClient()
    item = _find_supply(uid, active_client)
    result = active_client.update_task(
        "supplies",
        {
            "uid": item["uid"],
            "collectionId": item["collectionId"],
            "title": item["title"],
            "memo": item["memo"],
            "dueDate": "",
            "dueTime": "",
            "priority": "",
            "status": "COMPLETED" if mode == "done" else "NEEDS-ACTION",
        },
    )
    return {"ok": True, "item": {**item, "status": "COMPLETED" if mode == "done" else "NEEDS-ACTION", "done": mode == "done"}, "result": result}


def delete_supply_payload(uid: str, client: CalendarAdapterClient | None = None) -> dict[str, object]:
    active_client = client or CalendarAdapterClient()
    item = _find_supply(uid, active_client)
    result = active_client.delete_task("supplies", {"uid": item["uid"], "collectionId": item["collectionId"]})
    return {"ok": True, "deleted": True, "id": item["id"], "result": result}


def supply_state_path(path: str) -> tuple[str, str]:
    match = re.fullmatch(r"/api/supplies/([^/]+)/(active|done)", path)
    return (urllib.parse.unquote(match.group(1)), match.group(2)) if match else ("", "")


def supply_delete_uid(path: str) -> str:
    match = re.fullmatch(r"/api/supplies/([^/]+)", path)
    return urllib.parse.unquote(match.group(1)) if match else ""


def request_body(handler: BaseHTTPRequestHandler) -> bytes:
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except ValueError as exc:
        raise ValueError("invalid_body_length") from exc
    if length <= 0 or length > MAX_REQUEST_BYTES:
        raise ValueError("invalid_body_length")
    return handler.rfile.read(length)


def json_request(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    try:
        payload = json.loads(request_body(handler).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json_payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_json_payload")
    return payload


def multipart_form_request(
    handler: BaseHTTPRequestHandler,
    *,
    max_bytes: int,
) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    content_type = handler.headers.get("Content-Type") or ""
    if "multipart/form-data" not in content_type.lower():
        raise DocumentIntakeError("multipart_form_required")
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except ValueError as exc:
        raise ValueError("invalid_body_length") from exc
    if length <= 0 or length > max_bytes:
        raise ValueError("invalid_body_length")
    body = handler.rfile.read(length)
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    if not message.is_multipart():
        raise DocumentIntakeError("multipart_form_required")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is None:
            charset = part.get_content_charset() or "utf-8"
            fields[str(name)] = payload.decode(charset, errors="replace")
        else:
            files[str(name)] = (filename, payload)
    return fields, files


def ledger_status_for_error(exc: Exception) -> int:
    message = str(exc)
    if message == "ledger_entry_not_found":
        return 404
    if message == "ledger_revision_conflict":
        return 409
    if message == "family_profile_required":
        return 404
    return 400


def ledger_entry_id(path: str) -> str:
    match = re.fullmatch(r"/api/ledger/entries/([0-9a-z-]+)", path)
    return match.group(1) if match else ""


def memos_relay_error(handler: BaseHTTPRequestHandler, exc: memos_relay.MemosRelayError) -> None:
    json_response(handler, exc.status, {"ok": False, "error": exc.code, "message": exc.message})


def proxy_memos(handler: BaseHTTPRequestHandler, method: str) -> None:
    body = request_body(handler) if method in {"POST", "PATCH"} else None
    status, content_type, response_body = memos_relay.relay(
        method,
        handler.path,
        handler.headers,
        body=body,
    )
    bytes_response(handler, status, content_type, response_body, private=True)


@lru_cache(maxsize=1)
def paperless_service() -> PaperlessDocumentService:
    return PaperlessDocumentService(PaperlessConfig.from_env())


@lru_cache(maxsize=1)
def document_intake_store() -> DocumentIntakeStore:
    return DocumentIntakeStore(Path(os.environ.get("DOCUMENT_INTAKE_STATE_PATH", "/data/documents/intake.json")))


@lru_cache(maxsize=1)
def ai_task_archive() -> AITaskArchive:
    return AITaskArchive(Path(os.environ.get("AI_TASKS_STATE_PATH", "/data/ai-tasks/archive.json")))


def paperless_status_for_error(exc: Exception) -> int:
    if isinstance(exc, memos_relay.MemosRelayError):
        return exc.status
    code = exc.code if isinstance(exc, DocumentIntakeError) else str(exc)
    if code in {"main_profile_required", "paperless_document_not_found", "paperless_http_404"}:
        return 404
    if code in {
        "paperless_limit_invalid",
        "paperless_page_invalid",
        "paperless_query_too_long",
        "paperless_document_id_invalid",
        "multipart_form_required",
        "invalid_body_length",
        "pdf_attachment_required",
        "pdf_size_invalid",
        "invalid_pdf_signature",
        "paperless_tags_invalid",
        "paperless_metadata_required",
        "paperless_confirmation_required",
        "paperless_title_required",
        "paperless_record_not_found",
        "paperless_record_mismatch",
    }:
        return 400
    return 503


class OfficialSourceTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.skip_depth = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if normalized == "title":
            self.in_title = True
        if normalized in {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if normalized == "title":
            self.in_title = False
        if normalized in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = " ".join(str(data or "").split())
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        if not self.skip_depth:
            self.parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.title_parts).split())[:200]

    @property
    def text(self) -> str:
        return "\n".join(line.strip() for line in " ".join(self.parts).splitlines() if line.strip())


class OfficialAttachmentLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        href = values.get("href", "").strip()
        if not href:
            return
        parsed_href = urllib.parse.urlsplit(href)
        path = urllib.parse.unquote(parsed_href.path or "").lower()
        if not path.endswith((".pdf", ".hwpx", ".hwp", ".hml")):
            return
        filename = Path(urllib.parse.unquote(parsed_href.path)).name[:200]
        self.links.append(
            {
                "url": urllib.parse.urljoin(self.base_url, href),
                "filename": _safe_official_attachment_filename(filename),
            }
        )


def _safe_official_attachment_filename(filename: str) -> str:
    cleaned = " ".join(html.unescape(str(filename or "")).replace("\x00", "").split())
    return Path(cleaned).name[:200]


def _official_attachment_candidates(base_url: str, html_text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    parsed = urllib.parse.urlsplit(base_url)
    base_origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    for match in re.finditer(
        r"Header\.(?:goDown1?|goDownNew)\(\s*(['\"])(?P<src>.*?)\1\s*,\s*(['\"])(?P<filename>.*?)\3",
        html_text,
        flags=re.S,
    ):
        src = html.unescape(match.group("src")).strip()
        filename = _safe_official_attachment_filename(match.group("filename"))
        if not src or not filename:
            continue
        lowered = filename.lower()
        if not lowered.endswith((".pdf", ".hwpx", ".hwp", ".hml")):
            continue
        url = base_origin + "/download.do?" + urllib.parse.urlencode({"src": src, "fnm": filename})
        key = (url, filename)
        if key not in seen:
            seen.add(key)
            candidates.append({"url": url, "filename": filename})
        if len(candidates) >= OFFICIAL_MEMO_MAX_ATTACHMENTS:
            return candidates

    parser = OfficialAttachmentLinkParser(base_url)
    try:
        parser.feed(html_text)
    except Exception:
        return candidates
    for item in parser.links:
        key = (item["url"], item["filename"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(item)
        if len(candidates) >= OFFICIAL_MEMO_MAX_ATTACHMENTS:
            break
    return candidates


def _extract_hwpx_text(filename: str, content: bytes) -> str:
    if not content.startswith(b"PK"):
        raise AITaskError("ai_task_source_unsupported_content_type")
    parts: list[str] = []
    total_uncompressed = 0
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                lowered = name.lower()
                if info.is_dir():
                    continue
                if ".." in name.split("/"):
                    continue
                if not (
                    lowered == "preview/prvtext.txt"
                    or lowered.startswith("contents/")
                    and lowered.endswith((".xml", ".txt"))
                ):
                    continue
                total_uncompressed += max(0, int(info.file_size or 0))
                if total_uncompressed > OFFICIAL_MEMO_MAX_ATTACHMENT_BYTES:
                    raise AITaskError("ai_task_source_too_large")
                raw = archive.read(info, pwd=None)
                if lowered.endswith(".txt"):
                    text = raw.decode("utf-8", errors="replace")
                else:
                    text = _xml_text_content(raw)
                if text.strip():
                    parts.append(text)
                if sum(len(part) for part in parts) >= OFFICIAL_MEMO_MAX_ATTACHMENT_CHARS:
                    break
    except zipfile.BadZipFile as exc:
        raise AITaskError("ai_task_source_unsupported_content_type") from exc
    text = "\n".join(part.strip() for part in parts if part.strip())
    if not text.strip():
        raise AITaskError("ai_task_source_empty")
    return text[:OFFICIAL_MEMO_MAX_ATTACHMENT_CHARS]


def _xml_text_content(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text)
        values = [" ".join(part.split()) for part in root.itertext() if " ".join(part.split())]
        return "\n".join(values)
    except ET.ParseError:
        text = re.sub(r"<[^>]+>", " ", text)
        return "\n".join(line.strip() for line in html.unescape(text).splitlines() if line.strip())


def _extract_official_attachment_text(filename: str, content: bytes, content_type: str) -> str:
    lowered_name = filename.lower()
    lowered_type = content_type.lower()
    if lowered_name.endswith(".pdf") or "pdf" in lowered_type or content.startswith(b"%PDF-"):
        pdf_filename = filename if lowered_name.endswith(".pdf") else f"{filename}.pdf"
        return extract_official_memo_pdf_text(pdf_filename, content)[:OFFICIAL_MEMO_MAX_ATTACHMENT_CHARS]
    if lowered_name.endswith(".hwpx") or content.startswith(b"PK"):
        return _extract_hwpx_text(filename, content)
    if lowered_name.endswith(".hml") or "xml" in lowered_type:
        return _xml_text_content(content)[:OFFICIAL_MEMO_MAX_ATTACHMENT_CHARS]
    raise AITaskError("ai_task_source_unsupported_content_type")


def _fetch_official_source_attachments(
    base_url: str,
    html_text: str,
    *,
    require_allowed_health_host: bool,
    urlopen=urllib.request.urlopen,
) -> list[dict[str, object]]:
    attachments: list[dict[str, object]] = []
    for item in _official_attachment_candidates(base_url, html_text):
        url = item.get("url", "")
        filename = _safe_official_attachment_filename(item.get("filename", ""))
        if not url or not filename:
            continue
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"https", "http"} or not host:
            continue
        if _blocked_fetch_host(host):
            continue
        if require_allowed_health_host and not is_allowed_official_health_host(host):
            continue
        request = urllib.request.Request(
            urllib.parse.urlunsplit(parsed),
            headers={
                "Accept": "application/pdf, application/octet-stream;q=0.9, application/zip;q=0.8, text/xml;q=0.7, text/plain;q=0.6",
                "Referer": base_url,
                "User-Agent": "KaosGovernor/ai-tasks",
            },
        )
        try:
            with urlopen(request, timeout=OFFICIAL_MEMO_FETCH_TIMEOUT_SECONDS) as response:
                content_type = response.headers.get("Content-Type", "")
                content = response.read(OFFICIAL_MEMO_MAX_ATTACHMENT_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            continue
        if len(content) > OFFICIAL_MEMO_MAX_ATTACHMENT_BYTES:
            continue
        try:
            text = _extract_official_attachment_text(filename, content, content_type)
        except AITaskError:
            continue
        if not text.strip():
            continue
        attachments.append(
            {
                "filename": filename,
                "url": urllib.parse.urlunsplit(parsed),
                "host": host,
                "contentType": content_type,
                "textChars": len(text),
                "text": text,
            }
        )
        if len(attachments) >= OFFICIAL_MEMO_MAX_ATTACHMENTS:
            break
    return attachments


def ai_task_status_for_error(exc: Exception) -> int:
    if isinstance(exc, memos_relay.MemosRelayError):
        return exc.status
    code = exc.code if isinstance(exc, AITaskError) else str(exc)
    if code in {"main_profile_required", "ai_task_profile_required", "ai_task_not_found"}:
        return 404
    if code in {
        "invalid_body_length",
        "invalid_json_payload",
        "multipart_form_required",
        "ai_task_prompt_required",
        "ai_task_source_required",
        "ai_task_source_url_invalid",
        "ai_task_source_url_blocked",
        "ai_task_source_host_not_allowed",
        "ai_task_source_unsupported_content_type",
        "ai_task_source_too_large",
        "ai_task_source_not_found",
        "ai_task_source_empty",
        "ai_task_pdf_required",
        "ai_task_pdf_size_invalid",
        "ai_task_pdf_signature_invalid",
        "ai_task_pdf_reader_missing",
        "ai_task_pdf_text_empty",
        "ai_task_confirmation_required",
        "ai_task_limit_invalid",
        "web_task_prompt_required",
        "web_task_prompt_too_long",
        "official_web_sources_required",
        "ai_task_official_web_query_required",
        "ai_task_official_web_sources_not_found",
    }:
        return 400
    return 503


def ai_task_brain_token() -> str:
    if AI_TASKS_BRAIN_TOKEN:
        return AI_TASKS_BRAIN_TOKEN
    if AI_TASKS_BRAIN_TOKEN_FILE:
        try:
            return Path(AI_TASKS_BRAIN_TOKEN_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return secret_value("AI_TASKS_BRAIN_TOKEN")


def list_ai_tasks_payload(
    query_string: str = "",
    archive: AITaskArchive | None = None,
) -> dict[str, object]:
    active_archive = archive or ai_task_archive()
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    try:
        limit = int((params.get("limit") or ["50"])[0])
    except (TypeError, ValueError) as exc:
        raise AITaskError("ai_task_limit_invalid") from exc
    items = [record.as_dict() for record in active_archive.list_records(limit=limit)]
    return {"ok": True, "items": items, "totalCount": len(items)}


def ai_task_complete_id(path: str) -> str:
    match = re.fullmatch(r"/api/ai-tasks/([^/]+)/complete", path)
    return urllib.parse.unquote(match.group(1)) if match else ""


def complete_ai_task_payload(
    task_id: str,
    payload: dict[str, object],
    archive: AITaskArchive | None = None,
) -> dict[str, object]:
    if payload.get("confirmed") is not True:
        raise AITaskError("ai_task_confirmation_required")
    active_archive = archive or ai_task_archive()
    record = active_archive.complete(task_id, memo_name=str(payload.get("memoName") or ""))
    return {"ok": True, "applied": True, "task": record.as_dict()}


def _ai_task_prompt(payload: dict[str, object], *, web: bool = False) -> str:
    prompt = " ".join(str(payload.get("prompt") or "").split())
    if not prompt:
        raise AITaskError("web_task_prompt_required" if web else "ai_task_prompt_required")
    if web and len(prompt) > 1600:
        raise AITaskError("web_task_prompt_too_long")
    return prompt


def _payload_has_ai_task_source(payload: dict[str, object]) -> bool:
    pdf = payload.get("_sourcePdf")
    return bool(str(payload.get("sourceUrl") or "").strip() or str(payload.get("sourceText") or "").strip() or pdf)


def _ai_task_output_language(payload: Mapping[str, object]) -> str:
    value = str(payload.get("outputLanguage") or payload.get("language") or "").strip().lower()
    if value in {"ko", "korean", "한국어"} or payload.get("outputKorean") is True:
        return "ko"
    if value in {"en", "english"}:
        return "en"
    return ""


def _ai_task_running_source(payload: dict[str, object], *, source_task: bool) -> dict[str, object]:
    checked_at = datetime.now(UTC).date().isoformat()
    output_language = _ai_task_output_language(payload)
    language_hint = {"outputLanguage": output_language} if output_language else {}
    if not source_task:
        return {"type": "official_web_search", "checkedAt": checked_at, **language_hint}
    source_url = str(payload.get("sourceUrl") or "").strip()
    source_title = " ".join(str(payload.get("sourceTitle") or "").split())[:200]
    pdf = payload.get("_sourcePdf")
    if isinstance(pdf, tuple) and len(pdf) == 2:
        filename = Path(str(pdf[0] or "")).name[:200]
        return {"type": "pdf", "title": source_title or filename, "filename": filename, "checkedAt": checked_at, **language_hint}
    if str(payload.get("sourceText") or "").strip():
        return {"type": "text", "title": source_title or "Pasted official text", "url": source_url, "checkedAt": checked_at, **language_hint}
    return {"type": "url", "title": source_title or source_url, "url": source_url, "checkedAt": checked_at, **language_hint}


def _payload_with_extracted_pdf_source(payload: dict[str, object]) -> dict[str, object]:
    pdf = payload.get("_sourcePdf")
    if not isinstance(pdf, tuple) or len(pdf) != 2:
        return payload
    filename, content = pdf
    if not filename and not content:
        return payload
    text = extract_official_memo_pdf_text(str(filename or ""), bytes(content or b""))
    next_payload = {key: value for key, value in payload.items() if key != "_sourcePdf"}
    next_payload["sourceText"] = text
    next_payload["sourceType"] = "pdf"
    next_payload["sourceTitle"] = next_payload.get("sourceTitle") or Path(str(filename or "")).name[:200]
    next_payload["sourceFilename"] = Path(str(filename or "")).name[:200]
    return next_payload


def _official_doc_memo_result(
    prompt: str,
    payload: dict[str, object],
    *,
    urlopen=urllib.request.urlopen,
) -> tuple[dict[str, object], dict[str, object]]:
    source = official_memo_source_payload(payload, urlopen=urlopen)
    request = {
        "prompt": prompt,
        "checkedAt": datetime.now(UTC).date().isoformat(),
        "source": source,
    }
    output_language = _ai_task_output_language(payload)
    if output_language:
        request["outputLanguage"] = output_language
    memo = call_ai_task_brain(request, urlopen=urlopen)
    return {key: value for key, value in source.items() if key != "text"}, memo


def _web_ai_task_result(
    prompt: str,
    *,
    output_language: str = "",
    urlopen=urllib.request.urlopen,
) -> tuple[dict[str, object], dict[str, object]]:
    request = {
        "prompt": prompt,
        "checkedAt": datetime.now(UTC).date().isoformat(),
    }
    if output_language:
        request["outputLanguage"] = output_language
    plan_request = {
        **request,
        "allowedDomains": allowed_official_health_hosts(),
    }
    plan = _clean_official_web_plan(
        call_ai_task_official_web_brain("plan", plan_request, urlopen=urlopen),
        prompt=prompt,
        output_language=output_language,
    )
    source_payloads = fetch_official_web_sources(plan, urlopen=urlopen)
    textbook_sources = search_textbook_sources(prompt, plan)
    if not source_payloads and not textbook_sources:
        raise AITaskError("ai_task_official_web_sources_not_found")
    summary_request = {
        **request,
        "plan": plan,
        "sources": source_payloads,
        "textbookSources": textbook_sources,
    }
    result = _clean_official_web_result(
        call_ai_task_official_web_brain("summarize", summary_request, urlopen=urlopen),
        request=summary_request,
    )
    return {
        "type": "official_web_search",
        "checkedAt": result.get("checkedAt") or request["checkedAt"],
        "plan": plan,
        "sources": result.get("sources") if isinstance(result.get("sources"), list) else [],
        "textbookSources": textbook_sources,
    }, result


def _general_web_ai_task_result(
    prompt: str,
    *,
    output_language: str = "",
    urlopen=urllib.request.urlopen,
) -> tuple[dict[str, object], dict[str, object]]:
    request = {
        "prompt": prompt,
        "checkedAt": datetime.now(UTC).date().isoformat(),
    }
    if output_language:
        request["outputLanguage"] = output_language
    result = call_ai_task_web_brain(request, urlopen=urlopen)
    return {
        "type": "general_web_search",
        "checkedAt": result.get("checkedAt") or request["checkedAt"],
        "sources": result.get("sources") if isinstance(result.get("sources"), list) else [],
    }, result


def _ai_task_source_summaries(source_payloads: list[dict[str, object]], *, limit: int = 10) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for source in source_payloads:
        url = str(source.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        title = " ".join(str(source.get("title") or url).split())[:200]
        summaries.append({"title": title or url[:200], "url": url[:800]})
        if len(summaries) >= limit:
            break
    return summaries


def _official_web_failure_result(
    prompt: str,
    error: str,
    *,
    plan: dict[str, object] | None = None,
    source_payloads: list[dict[str, object]] | None = None,
    textbook_sources: list[dict[str, object]] | None = None,
    checked_at: str = "",
) -> dict[str, object]:
    sources = _ai_task_source_summaries(source_payloads or [])
    textbook_sources = list(textbook_sources or [])
    if not sources and not textbook_sources:
        return {}
    plan_query = str((plan or {}).get("query") or prompt).strip()
    lines = [
        f"KaosBrain summary failed: {error}",
        "",
        "Governor did find readable source material. Use the references below, adjust the prompt, or run supplemental SEARCH WEB from this card.",
    ]
    if plan_query:
        lines.extend(["", f"Search query: {plan_query}"])
    if sources:
        lines.append("")
        lines.append("Official/current sources found:")
        for index, source in enumerate(sources, start=1):
            lines.append(f"{index}. {source['title']} — {source['url']}")
    if textbook_sources:
        lines.append("")
        lines.append("Textbook background found:")
        for index, source in enumerate(textbook_sources[:5], start=1):
            citation = str(source.get("citation") or source.get("title") or "Harrison").strip()
            lines.append(f"{index}. {citation}")
    return {
        "title": "Official sources found; summary failed",
        "content": "\n".join(lines),
        "sources": sources,
        "textbookSources": textbook_sources[:5],
        "checkedAt": checked_at or datetime.now(UTC).date().isoformat(),
        "model": "kaosgovernor-source-fallback",
    }


def preview_official_doc_memo_payload(
    payload: dict[str, object],
    archive: AITaskArchive | None = None,
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    prompt = _ai_task_prompt(payload)
    source, memo = _official_doc_memo_result(prompt, payload, urlopen=urlopen)
    record = (archive or ai_task_archive()).add_preview(
        kind="official_doc_memo",
        prompt=prompt,
        source=source,
        memo=memo,
    )
    return {"ok": True, "task": record.as_dict(), "memo": memo}


def preview_web_ai_task_payload(
    payload: dict[str, object],
    archive: AITaskArchive | None = None,
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    prompt = _ai_task_prompt(payload, web=True)
    source, result = _web_ai_task_result(prompt, output_language=_ai_task_output_language(payload), urlopen=urlopen)
    record = (archive or ai_task_archive()).add_result(
        kind="web",
        prompt=prompt,
        source=source,
        result=result,
    )
    return {"ok": True, "task": record.as_dict(), "result": result}


def preview_general_web_ai_task_payload(
    payload: dict[str, object],
    archive: AITaskArchive | None = None,
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    prompt = _ai_task_prompt(payload, web=True)
    output_language = _ai_task_output_language(payload)
    active_archive = archive or ai_task_archive()
    try:
        source, result = _general_web_ai_task_result(prompt, output_language=output_language, urlopen=urlopen)
    except AITaskError as exc:
        record = active_archive.add_running(
            kind="general_web",
            prompt=prompt,
            source={
                "type": "general_web_search",
                "checkedAt": datetime.now(UTC).date().isoformat(),
            },
        )
        failed = active_archive.fail(record.task_id, error=exc.code)
        return {"ok": True, "task": failed.as_dict(), "result": {}}
    record = active_archive.add_result(
        kind="general_web",
        prompt=prompt,
        source=source,
        result=result,
    )
    return {"ok": True, "task": record.as_dict(), "result": result}


def run_ai_task_worker(
    task_id: str,
    payload: dict[str, object],
    *,
    source_task: bool,
    archive: AITaskArchive | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    active_archive = archive or ai_task_archive()
    partial_source: dict[str, object] | None = None
    partial_result: dict[str, object] | None = None
    prompt = ""
    try:
        if source_task:
            next_payload = _payload_with_extracted_pdf_source(payload)
            prompt = _ai_task_prompt(next_payload)
            source, memo = _official_doc_memo_result(prompt, next_payload, urlopen=urlopen)
            active_archive.finish_preview(task_id, source=source, memo=memo)
        else:
            prompt = _ai_task_prompt(payload, web=True)
            request = {
                "prompt": prompt,
                "checkedAt": datetime.now(UTC).date().isoformat(),
            }
            output_language = _ai_task_output_language(payload)
            if output_language:
                request["outputLanguage"] = output_language
            plan_request = {
                **request,
                "allowedDomains": allowed_official_health_hosts(),
            }
            plan = _clean_official_web_plan(
                call_ai_task_official_web_brain("plan", plan_request, urlopen=urlopen),
                prompt=prompt,
                output_language=output_language,
            )
            partial_source = {
                "type": "official_web_search",
                "checkedAt": request["checkedAt"],
                "plan": plan,
                "sources": [],
            }
            source_payloads = fetch_official_web_sources(plan, urlopen=urlopen)
            partial_source["sources"] = _ai_task_source_summaries(source_payloads)
            textbook_sources = search_textbook_sources(prompt, plan)
            partial_source["textbookSources"] = textbook_sources
            if not source_payloads and not textbook_sources:
                raise AITaskError("ai_task_official_web_sources_not_found")
            summary_request = {
                **request,
                "plan": plan,
                "sources": source_payloads,
                "textbookSources": textbook_sources,
            }
            try:
                result = _clean_official_web_result(
                    call_ai_task_official_web_brain("summarize", summary_request, urlopen=urlopen),
                    request=summary_request,
                )
            except AITaskError as exc:
                partial_result = _official_web_failure_result(
                    prompt,
                    exc.code,
                    plan=plan,
                    source_payloads=source_payloads,
                    textbook_sources=textbook_sources,
                    checked_at=request["checkedAt"],
                )
                raise
            source = {
                "type": "official_web_search",
                "checkedAt": result.get("checkedAt") or request["checkedAt"],
                "plan": plan,
                "sources": result.get("sources") if isinstance(result.get("sources"), list) else [],
                "textbookSources": textbook_sources,
            }
            if not source["sources"]:
                source["sources"] = _ai_task_source_summaries(source_payloads)
            active_archive.finish_result(task_id, source=source, result=result)
    except AITaskError as exc:
        fail_kwargs: dict[str, object] = {}
        if partial_source is not None:
            fail_kwargs["source"] = partial_source
        if partial_result:
            fail_kwargs["result"] = partial_result
            fail_kwargs["memo"] = {
                "title": str(partial_result.get("title") or "AI Task"),
                "content": str(partial_result.get("content") or ""),
            }
        active_archive.fail(task_id, error=exc.code, **fail_kwargs)
    except Exception as exc:
        print(f"AI task worker failed: {type(exc).__name__}", flush=True)
        try:
            partial_result = _official_web_failure_result(
                prompt,
                "ai_task_background_failed",
                source_payloads=(partial_source or {}).get("sources") if isinstance((partial_source or {}).get("sources"), list) else [],
                textbook_sources=(partial_source or {}).get("textbookSources") if isinstance((partial_source or {}).get("textbookSources"), list) else [],
            )
            fail_kwargs = {"source": partial_source} if partial_source is not None else {}
            if partial_result:
                fail_kwargs["result"] = partial_result
            active_archive.fail(task_id, error="ai_task_background_failed", **fail_kwargs)
        except AITaskError:
            pass


def start_ai_task_payload(
    payload: dict[str, object],
    archive: AITaskArchive | None = None,
    *,
    start_worker: bool = True,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    source_task = _payload_has_ai_task_source(payload)
    prompt = _ai_task_prompt(payload, web=not source_task)
    active_archive = archive or ai_task_archive()
    record = active_archive.add_running(
        kind="official_doc_memo" if source_task else "web",
        prompt=prompt,
        source=_ai_task_running_source(payload, source_task=source_task),
    )
    if start_worker:
        threading.Thread(
            target=run_ai_task_worker,
            kwargs={
                "task_id": record.task_id,
                "payload": payload,
                "source_task": source_task,
                "archive": active_archive,
                "urlopen": urlopen,
            },
            daemon=True,
        ).start()
    return {"ok": True, "accepted": True, "task": record.as_dict()}


def _clean_official_web_plan(plan: dict[str, object], *, prompt: str, output_language: str = "") -> dict[str, object]:
    query = " ".join(str(plan.get("query") or prompt).split())[:200]
    if not query:
        raise AITaskError("ai_task_official_web_query_required")
    alternate_queries = _clean_string_list(plan.get("alternateQueries"), limit=3, max_chars=200)
    preferred_domains = [
        host
        for host in _clean_string_list(plan.get("preferredDomains"), limit=6, max_chars=120)
        if is_allowed_official_health_host(host)
    ]
    task = str(plan.get("task") or "summary").strip().lower()
    if task not in {"summary", "list", "explain", "compare", "treatment_options"}:
        task = "summary"
    if task == "summary" and looks_like_treatment_options_query(query, alternate_queries):
        task = "treatment_options"
    language = str(plan.get("language") or "ko").strip().lower()
    if language not in {"ko", "en"}:
        language = "ko"
    if output_language in {"ko", "en"}:
        language = output_language
    return {
        "query": query,
        "alternateQueries": alternate_queries,
        "preferredDomains": preferred_domains,
        "task": task,
        "language": language,
    }


def _clean_official_web_result(result: dict[str, object], *, request: dict[str, object]) -> dict[str, object]:
    title = " ".join(str(result.get("title") or "").split())
    content = str(result.get("content") or "").strip()
    if not title or not content:
        raise AITaskError("ai_task_official_web_invalid_result")
    sources = []
    for source in result.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        host = urllib.parse.urlsplit(url).hostname or ""
        if not url.startswith(("https://", "http://")) or not is_allowed_official_health_host(host):
            continue
        sources.append({"title": " ".join(str(source.get("title") or url).split())[:200], "url": url[:800]})
        if len(sources) >= 10:
            break
    if not sources:
        for source in request.get("sources") or []:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").strip()
            if url.startswith(("https://", "http://")):
                sources.append({"title": " ".join(str(source.get("title") or url).split())[:200], "url": url[:800]})
            if len(sources) >= 10:
                break
    return {
        "title": title[:160],
        "content": content[:12000],
        "sources": sources,
        "checkedAt": str(result.get("checkedAt") or request.get("checkedAt") or "").strip()[:40],
        "model": str(result.get("model") or "kaosbrain-openai").strip()[:80],
    }


def _clean_string_list(value: object, *, limit: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split())[:max_chars]
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def fetch_official_web_sources(plan: dict[str, object], *, urlopen=urllib.request.urlopen) -> list[dict[str, object]]:
    candidates = official_health_search_candidates(
        str(plan.get("query") or ""),
        alternate_queries=_clean_string_list(plan.get("alternateQueries"), limit=3, max_chars=200),
        preferred_domains=_clean_string_list(plan.get("preferredDomains"), limit=6, max_chars=120),
        limit=8,
        urlopen=urlopen,
    )
    sources: list[dict[str, object]] = []
    for candidate in candidates:
        try:
            source = fetch_official_source(
                candidate.url,
                title=candidate.title,
                require_allowed_health_host=True,
                urlopen=urlopen,
            )
        except AITaskError:
            continue
        source["searchScore"] = candidate.score
        source["searchSource"] = candidate.source
        sources.append(source)
        if len(sources) >= 5:
            break
    return sources


def preview_official_doc_memo_request_payload(
    handler: BaseHTTPRequestHandler,
    archive: AITaskArchive | None = None,
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    content_type = handler.headers.get("Content-Type") or ""
    if "multipart/form-data" not in content_type.lower():
        return preview_official_doc_memo_payload(json_request(handler), archive, urlopen=urlopen)
    fields, files = multipart_form_request(handler, max_bytes=OFFICIAL_MEMO_MAX_PDF_BYTES + MAX_MULTIPART_OVERHEAD_BYTES)
    payload: dict[str, object] = {
        "prompt": fields.get("prompt") or "",
        "sourceUrl": fields.get("sourceUrl") or "",
        "sourceTitle": fields.get("sourceTitle") or "",
        "outputLanguage": fields.get("outputLanguage") or "",
    }
    filename, content = files.get("sourcePdf") or files.get("pdf") or files.get("file") or ("", b"")
    if filename or content:
        text = extract_official_memo_pdf_text(filename, content)
        payload["sourceText"] = text
        payload["sourceType"] = "pdf"
        payload["sourceTitle"] = payload["sourceTitle"] or filename
        payload["sourceFilename"] = filename
    else:
        payload["sourceText"] = fields.get("sourceText") or ""
    return preview_official_doc_memo_payload(payload, archive, urlopen=urlopen)


def start_ai_task_request_payload(
    handler: BaseHTTPRequestHandler,
    archive: AITaskArchive | None = None,
    *,
    start_worker: bool = True,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    content_type = handler.headers.get("Content-Type") or ""
    if "multipart/form-data" not in content_type.lower():
        return start_ai_task_payload(json_request(handler), archive, start_worker=start_worker, urlopen=urlopen)
    fields, files = multipart_form_request(handler, max_bytes=OFFICIAL_MEMO_MAX_PDF_BYTES + MAX_MULTIPART_OVERHEAD_BYTES)
    payload: dict[str, object] = {
        "prompt": fields.get("prompt") or "",
        "sourceUrl": fields.get("sourceUrl") or "",
        "sourceTitle": fields.get("sourceTitle") or "",
        "sourceText": fields.get("sourceText") or "",
        "outputLanguage": fields.get("outputLanguage") or "",
    }
    filename, content = files.get("sourcePdf") or files.get("pdf") or files.get("file") or ("", b"")
    if filename or content:
        payload["_sourcePdf"] = (Path(filename).name[:200], content)
    return start_ai_task_payload(payload, archive, start_worker=start_worker, urlopen=urlopen)


def official_memo_source_payload(
    payload: dict[str, object],
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    source_text = str(payload.get("sourceText") or "").strip()
    source_url = str(payload.get("sourceUrl") or "").strip()
    source_title = " ".join(str(payload.get("sourceTitle") or "").split())[:200]
    source_filename = Path(str(payload.get("sourceFilename") or "")).name[:200]
    if source_text:
        return {
            "type": _clean_ai_source_type(payload.get("sourceType")) or "text",
            "title": source_title or source_filename or "Pasted official text",
            "url": source_url,
            "filename": source_filename,
            "text": source_text[:OFFICIAL_MEMO_MAX_SOURCE_CHARS],
        }
    if source_url:
        return fetch_official_source(source_url, title=source_title, urlopen=urlopen)
    raise AITaskError("ai_task_source_required")


def extract_official_memo_pdf_text(filename: str, content: bytes) -> str:
    if not filename or not content:
        raise AITaskError("ai_task_pdf_required")
    if not str(filename).lower().endswith(".pdf"):
        raise AITaskError("ai_task_pdf_required")
    if len(content) <= 0 or len(content) > OFFICIAL_MEMO_MAX_PDF_BYTES:
        raise AITaskError("ai_task_pdf_size_invalid")
    if not content.startswith(b"%PDF-"):
        raise AITaskError("ai_task_pdf_signature_invalid")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise AITaskError("ai_task_pdf_reader_missing") from exc
    try:
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages[:50]:
            parts.append(page.extract_text() or "")
    except Exception as exc:
        raise AITaskError("ai_task_pdf_text_empty") from exc
    text = "\n".join(part.strip() for part in parts if part.strip())
    if not text.strip():
        raise AITaskError("ai_task_pdf_text_empty")
    return text[:OFFICIAL_MEMO_MAX_SOURCE_CHARS]


def _clean_ai_source_type(value: object) -> str:
    source_type = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"_", "-"})[:40]
    return source_type if source_type in {"text", "pdf"} else ""


def fetch_official_source(
    source_url: str,
    *,
    title: str = "",
    require_allowed_health_host: bool = False,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise AITaskError("ai_task_source_url_invalid")
    host = parsed.hostname.lower().rstrip(".")
    if _blocked_fetch_host(host):
        raise AITaskError("ai_task_source_url_blocked")
    if require_allowed_health_host and not is_allowed_official_health_host(host):
        raise AITaskError("ai_task_source_host_not_allowed")
    if host == "pubmed.ncbi.nlm.nih.gov":
        pubmed_source = _fetch_pubmed_eutils_source(parsed, title=title, urlopen=urlopen)
        if pubmed_source:
            return pubmed_source
    request = urllib.request.Request(
        urllib.parse.urlunsplit(parsed),
        headers={
            "Accept": "text/html, text/plain;q=0.9, application/json;q=0.8, application/pdf;q=0.7, application/octet-stream;q=0.6",
            "User-Agent": "KaosGovernor/ai-tasks",
        },
    )
    try:
        with urlopen(request, timeout=OFFICIAL_MEMO_FETCH_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            lowered_path = urllib.parse.unquote(parsed.path or "").lower()
            attachment_like = lowered_path.endswith((".pdf", ".hwpx", ".hwp", ".hml"))
            read_limit = OFFICIAL_MEMO_MAX_ATTACHMENT_BYTES if attachment_like or "pdf" in content_type.lower() else 1_000_000
            raw = response.read(read_limit + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AITaskError("ai_task_source_fetch_failed") from exc
    lower_type = content_type.lower()
    lowered_path = urllib.parse.unquote(parsed.path or "").lower()
    attachment_like = lowered_path.endswith((".pdf", ".hwpx", ".hwp", ".hml"))
    if len(raw) > (OFFICIAL_MEMO_MAX_ATTACHMENT_BYTES if attachment_like or "pdf" in lower_type else 1_000_000):
        raise AITaskError("ai_task_source_too_large")
    if lower_type and not any(
        kind in lower_type
        for kind in ("text/html", "text/plain", "application/json", "application/pdf", "application/octet-stream", "application/zip", "text/xml")
    ):
        raise AITaskError("ai_task_source_unsupported_content_type")
    if "pdf" in lower_type or raw.startswith(b"%PDF-"):
        filename = Path(urllib.parse.unquote(parsed.path)).name or "official-source.pdf"
        text = extract_official_memo_pdf_text(filename if filename.lower().endswith(".pdf") else f"{filename}.pdf", raw)
        return {
            "type": "url_pdf",
            "title": title or filename or host,
            "url": urllib.parse.urlunsplit(parsed),
            "host": host,
            "text": text[:OFFICIAL_MEMO_MAX_SOURCE_CHARS],
        }
    if lowered_path.endswith(".hwp") and not lowered_path.endswith(".hwpx"):
        raise AITaskError("ai_task_source_unsupported_content_type")
    if lowered_path.endswith((".hwpx", ".hml")) or (raw.startswith(b"PK") and "html" not in lower_type):
        filename = Path(urllib.parse.unquote(parsed.path)).name or "official-source.hwpx"
        text = _extract_official_attachment_text(filename, raw, content_type)
        return {
            "type": "url_hwpx" if filename.lower().endswith(".hwpx") or raw.startswith(b"PK") else "url_hml",
            "title": title or filename or host,
            "url": urllib.parse.urlunsplit(parsed),
            "host": host,
            "filename": filename,
            "text": text[:OFFICIAL_MEMO_MAX_SOURCE_CHARS],
        }
    text = _decode_http_text(raw, content_type)
    attachment_payloads: list[dict[str, object]] = []
    if "html" in lower_type or "<html" in text[:500].lower():
        html_text = text
        parser = OfficialSourceTextParser()
        parser.feed(html_text)
        text = parser.text
        title = title or parser.title
        attachments = _fetch_official_source_attachments(
            urllib.parse.urlunsplit(parsed),
            html_text,
            require_allowed_health_host=require_allowed_health_host,
            urlopen=urlopen,
        )
        if attachments:
            attachment_sections = [
                f"첨부파일: {item['filename']}\n{item['text']}"
                for item in attachments
                if str(item.get("text") or "").strip()
            ]
            if attachment_sections:
                text = "\n\n".join([text[:OFFICIAL_MEMO_MAX_SOURCE_CHARS], *attachment_sections])
            attachment_payloads = [{key: value for key, value in item.items() if key != "text"} for item in attachments]
    else:
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not text.strip():
        raise AITaskError("ai_task_source_empty")
    normalized_text = " ".join(text.split())
    if host == "pubmed.ncbi.nlm.nih.gov" and (
        "Cookies must be enabled" in normalized_text or "Clipboard, Search History" in normalized_text
    ):
        raise AITaskError("ai_task_source_empty")
    if host.endswith("entnet.org") and (
        normalized_text.startswith("You searched for ") or "Submit site search" in normalized_text[:400]
    ):
        raise AITaskError("ai_task_source_empty")
    if (title == "알림메세지" and "존재 하지 않습니다" in normalized_text) or "게시물이 존재하지 않습니다" in normalized_text:
        raise AITaskError("ai_task_source_not_found")
    source_payload: dict[str, object] = {
        "type": "url",
        "title": title or host,
        "url": urllib.parse.urlunsplit(parsed),
        "host": host,
        "text": text[:OFFICIAL_MEMO_MAX_SOURCE_CHARS],
    }
    if attachment_payloads:
        source_payload["attachments"] = attachment_payloads
    return source_payload


def _fetch_pubmed_eutils_source(
    parsed: urllib.parse.SplitResult,
    *,
    title: str = "",
    urlopen=urllib.request.urlopen,
) -> dict[str, object] | None:
    pmid_match = re.match(r"^/(\d{6,12})/?$", parsed.path or "")
    if not pmid_match:
        return None
    pmid = pmid_match.group(1)
    url = urllib.parse.urlunsplit(parsed)
    eutils_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
        + urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "xml"})
    )
    request = urllib.request.Request(
        eutils_url,
        headers={
            "Accept": "application/xml, text/xml;q=0.9",
            "User-Agent": "KaosGovernor/ai-tasks pubmed-eutils",
        },
    )
    try:
        with urlopen(request, timeout=OFFICIAL_MEMO_FETCH_TIMEOUT_SECONDS) as response:
            raw = response.read(1_000_000)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    article_title = " ".join("".join(root.findtext(".//ArticleTitle") or "").split())
    journal = " ".join("".join(root.findtext(".//Journal/Title") or "").split())
    pub_date = _pubmed_publication_date(root)
    article_types = [
        " ".join("".join(item.itertext()).split())
        for item in root.findall(".//PublicationTypeList/PublicationType")
        if " ".join("".join(item.itertext()).split())
    ]
    abstract_parts: list[str] = []
    for node in root.findall(".//Abstract/AbstractText"):
        body = " ".join("".join(node.itertext()).split())
        if not body:
            continue
        label = str(node.attrib.get("Label") or "").strip()
        abstract_parts.append(f"{label}: {body}" if label else body)
    mesh_terms = [
        " ".join("".join(node.findtext("DescriptorName") or "").split())
        for node in root.findall(".//MeshHeading")
        if " ".join("".join(node.findtext("DescriptorName") or "").split())
    ][:12]
    if not abstract_parts:
        return None
    parts = [
        article_title,
        f"PMID: {pmid}",
        f"Journal: {journal}" if journal else "",
        f"Publication date: {pub_date}" if pub_date else "",
        f"Publication type: {', '.join(article_types[:6])}" if article_types else "",
        "Abstract:",
        *abstract_parts,
        f"MeSH terms: {', '.join(mesh_terms)}" if mesh_terms else "",
    ]
    text = "\n".join(part for part in parts if part)
    return {
        "type": "pubmed",
        "title": title or article_title or f"PubMed PMID {pmid}",
        "url": url,
        "host": "pubmed.ncbi.nlm.nih.gov",
        "text": text[:OFFICIAL_MEMO_MAX_SOURCE_CHARS],
    }


def _pubmed_publication_date(root: ET.Element) -> str:
    pub_date = root.find(".//JournalIssue/PubDate")
    if pub_date is None:
        pub_date = root.find(".//ArticleDate")
    if pub_date is None:
        return ""
    year = " ".join("".join(pub_date.findtext("Year") or "").split())
    month = " ".join("".join(pub_date.findtext("Month") or "").split())
    day = " ".join("".join(pub_date.findtext("Day") or "").split())
    medline = " ".join("".join(pub_date.findtext("MedlineDate") or "").split())
    return " ".join(part for part in (year, month, day) if part) or medline


def _decode_http_text(raw: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type or "", flags=re.I)
    charset = match.group(1) if match else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _blocked_fetch_host(host: str) -> bool:
    if host in {"localhost"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return False
        for item in resolved:
            try:
                address = ipaddress.ip_address(item[4][0])
            except ValueError:
                return True
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                return True
        return False
    return address.is_private or address.is_loopback or address.is_link_local or address.is_reserved


def call_ai_task_brain(
    request_payload: dict[str, object],
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    if not AI_TASKS_BRAIN_URL:
        raise AITaskError("ai_task_brain_not_configured")
    token = ai_task_brain_token()
    if not token:
        raise AITaskError("ai_task_brain_token_missing")
    request = urllib.request.Request(
        AI_TASKS_BRAIN_URL,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "KaosGovernor/ai-tasks",
        },
    )
    try:
        with urlopen(request, timeout=AI_TASKS_BRAIN_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            code = str(body.get("error") or f"ai_task_brain_http_{exc.code}")
        except Exception:
            code = f"ai_task_brain_http_{exc.code}"
        raise AITaskError(code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AITaskError("ai_task_brain_request_failed") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AITaskError("ai_task_brain_invalid_json") from exc
    if not isinstance(body, dict) or body.get("ok") is not True:
        error = str(body.get("error") or "ai_task_brain_failed") if isinstance(body, dict) else "ai_task_brain_invalid_response"
        raise AITaskError(error)
    memo = body.get("memo")
    if not isinstance(memo, dict):
        raise AITaskError("ai_task_brain_missing_memo")
    title = " ".join(str(memo.get("title") or "").split())
    content = str(memo.get("content") or "").strip()
    if not title or not content:
        raise AITaskError("ai_task_brain_invalid_memo")
    return {
        "title": title[:160],
        "content": content[:7900],
        "sourceTitle": " ".join(str(memo.get("sourceTitle") or "").split())[:200],
        "sourceUrl": str(memo.get("sourceUrl") or "").strip()[:500],
        "checkedAt": str(memo.get("checkedAt") or request_payload.get("checkedAt") or "").strip()[:40],
    }


def ai_tasks_web_brain_url() -> str:
    if AI_TASKS_WEB_BRAIN_URL:
        return AI_TASKS_WEB_BRAIN_URL
    marker = "/internal/ai-tasks/official-doc-memo/preview"
    if AI_TASKS_BRAIN_URL.endswith(marker):
        return f"{AI_TASKS_BRAIN_URL.removesuffix(marker)}/internal/ai-tasks/web/preview"
    return ""


def ai_tasks_official_web_brain_url(kind: str) -> str:
    base = ""
    marker = "/internal/ai-tasks/official-doc-memo/preview"
    if AI_TASKS_BRAIN_URL.endswith(marker):
        base = AI_TASKS_BRAIN_URL.removesuffix(marker)
    elif AI_TASKS_WEB_BRAIN_URL.endswith("/internal/ai-tasks/web/preview"):
        base = AI_TASKS_WEB_BRAIN_URL.removesuffix("/internal/ai-tasks/web/preview")
    if not base:
        return ""
    return f"{base}/internal/ai-tasks/official-web/{kind}"


def call_ai_task_official_web_brain(
    kind: str,
    request_payload: dict[str, object],
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    brain_url = ai_tasks_official_web_brain_url(kind)
    if not brain_url:
        raise AITaskError("ai_task_official_web_brain_not_configured")
    token = ai_task_brain_token()
    if not token:
        raise AITaskError("ai_task_brain_token_missing")
    request = urllib.request.Request(
        brain_url,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "KaosGovernor/ai-tasks",
        },
    )
    retryable_errors = {
        "ai_task_official_web_brain_http_502",
        "ai_task_official_web_brain_http_503",
        "ai_task_official_web_brain_http_504",
        "ai_task_official_web_brain_request_failed",
        "kaosbrain_official_web_plan_unavailable",
        "kaosbrain_official_web_summary_unavailable",
    }
    raw = b""
    for attempt in range(2):
        try:
            with urlopen(request, timeout=AI_TASKS_BRAIN_TIMEOUT_SECONDS) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
                code = str(body.get("error") or f"ai_task_official_web_brain_http_{exc.code}")
            except Exception:
                code = f"ai_task_official_web_brain_http_{exc.code}"
            if attempt == 0 and (code in retryable_errors or exc.code in {502, 503, 504}):
                continue
            raise AITaskError(code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 0:
                continue
            raise AITaskError("ai_task_official_web_brain_request_failed") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AITaskError("ai_task_official_web_brain_invalid_json") from exc
    if not isinstance(body, dict) or body.get("ok") is not True:
        error = str(body.get("error") or "ai_task_official_web_brain_failed") if isinstance(body, dict) else "ai_task_official_web_brain_invalid_response"
        raise AITaskError(error)
    expected_key = "plan" if kind == "plan" else "result"
    value = body.get(expected_key)
    if not isinstance(value, dict):
        raise AITaskError(f"ai_task_official_web_missing_{expected_key}")
    return value


def call_ai_task_web_brain(
    request_payload: dict[str, object],
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    brain_url = ai_tasks_web_brain_url()
    if not brain_url:
        raise AITaskError("ai_task_web_brain_not_configured")
    token = ai_task_brain_token()
    if not token:
        raise AITaskError("ai_task_brain_token_missing")
    request = urllib.request.Request(
        brain_url,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "KaosGovernor/ai-tasks",
        },
    )
    retryable_errors = {
        "ai_task_web_brain_http_502",
        "ai_task_web_brain_http_503",
        "ai_task_web_brain_http_504",
        "ai_task_web_brain_request_failed",
        "kaosbrain_web_search_unavailable",
        "web_task_openai_timeout",
        "web_task_openai_request_failed",
    }
    raw = b""
    for attempt in range(2):
        try:
            with urlopen(request, timeout=AI_TASKS_BRAIN_TIMEOUT_SECONDS) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
                code = str(body.get("error") or f"ai_task_web_brain_http_{exc.code}")
            except Exception:
                code = f"ai_task_web_brain_http_{exc.code}"
            if attempt == 0 and code in retryable_errors:
                continue
            raise AITaskError(code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 0:
                continue
            raise AITaskError("ai_task_web_brain_request_failed") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AITaskError("ai_task_web_brain_invalid_json") from exc
    if not isinstance(body, dict) or body.get("ok") is not True:
        error = str(body.get("error") or "ai_task_web_brain_failed") if isinstance(body, dict) else "ai_task_web_brain_invalid_response"
        raise AITaskError(error)
    result = body.get("result")
    if not isinstance(result, dict):
        raise AITaskError("ai_task_web_brain_missing_result")
    title = " ".join(str(result.get("title") or "").split())
    content = str(result.get("content") or "").strip()
    if not title or not content:
        raise AITaskError("ai_task_web_brain_invalid_result")
    sources = result.get("sources")
    if not isinstance(sources, list):
        sources = []
    clean_sources: list[dict[str, str]] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        clean_sources.append(
            {
                "title": " ".join(str(item.get("title") or url).split())[:200],
                "url": url[:800],
            }
        )
        if len(clean_sources) >= 10:
            break
    return {
        "title": title[:160],
        "content": content[:12000],
        "sources": clean_sources,
        "checkedAt": str(result.get("checkedAt") or request_payload.get("checkedAt") or "").strip()[:40],
        "model": str(result.get("model") or "").strip()[:80],
    }


def _paperless_query_int(params: dict[str, list[str]], name: str, default: int) -> int:
    raw = (params.get(name) or [str(default)])[0]
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise DocumentIntakeError(f"paperless_{name}_invalid") from exc


def paperless_document_url(service: PaperlessDocumentService, document_id: int) -> str:
    base = service.config.public_url.rstrip("/")
    return f"{base}/documents/{document_id}/details" if base else ""


def paperless_inbox_item_payload(record, service: PaperlessDocumentService) -> dict[str, object]:
    item = record.as_dict()
    document_id = int(item.get("documentId") or 0)
    item["url"] = paperless_document_url(service, document_id) if document_id else ""
    return item


def paperless_page_payload(
    query_string: str,
    service: PaperlessDocumentService | None = None,
) -> dict[str, object]:
    active_service = service or paperless_service()
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    query = " ".join((params.get("query") or [""])[0].split())
    tag_names = paperless_query_tag_names(params)
    tag_ids = paperless_query_tag_ids(active_service, tag_names)
    page_number = _paperless_query_int(params, "page", 1)
    limit = _paperless_query_int(params, "limit", 20)
    if tag_names and not tag_ids:
        total_page = active_service.list_page(limit=1, page=1)
        return {
            "ok": True,
            "query": query,
            "items": [],
            "resultCount": 0,
            "totalCount": total_page.total_count,
            "page": page_number,
            "pageSize": limit,
            "selectedTags": list(tag_names),
        }
    page = (
        active_service.search_page(query, limit=limit, page=page_number, tag_ids=tag_ids)
        if query
        else active_service.list_page(limit=limit, page=page_number, tag_ids=tag_ids)
    )
    items: list[dict[str, object]] = []
    for result in page.results:
        item = result.as_dict()
        item["url"] = paperless_document_url(active_service, result.document_id)
        items.append(item)
    return {
        "ok": True,
        "query": page.query,
        "items": items,
        "resultCount": page.result_count,
        "totalCount": page.total_count,
        "page": page.page,
        "pageSize": page.page_size,
        "selectedTags": list(tag_names),
    }


def paperless_tags_payload(
    service: PaperlessDocumentService | None = None,
) -> dict[str, object]:
    active_service = service or paperless_service()
    return {"ok": True, "items": [tag.as_dict() for tag in active_service.list_tags()]}


def paperless_document_payload(
    document_id: str,
    service: PaperlessDocumentService | None = None,
) -> dict[str, object]:
    active_service = service or paperless_service()
    document = active_service.get(document_id)
    payload = document.as_dict()
    payload["url"] = paperless_document_url(active_service, document.document_id)
    return {"ok": True, "document": payload}


def paperless_metadata_path(path: str) -> tuple[str, str]:
    match = re.fullmatch(r"/api/paperless/documents/([1-9][0-9]*)/metadata/(proposal|apply)", path)
    return (match.group(1), match.group(2)) if match else ("", "")


def paperless_tag_suggestion_path(path: str) -> str:
    match = re.fullmatch(r"/api/paperless/documents/([1-9][0-9]*)/metadata/tag-suggestions", path)
    return match.group(1) if match else ""


def paperless_metadata_tags(payload: dict[str, object]) -> tuple[str, ...]:
    raw_tags = payload.get("tags") or []
    if not isinstance(raw_tags, list):
        raise DocumentIntakeError("paperless_tags_invalid")
    tags: list[str] = []
    for value in raw_tags:
        tag = " ".join(str(value or "").strip().lstrip("#").split())
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags[:25])


def paperless_query_tag_names(params: dict[str, list[str]]) -> tuple[str, ...]:
    names: list[str] = []
    for raw in [*(params.get("tag") or []), *(params.get("tags") or [])]:
        for value in str(raw or "").replace(",", "\n").splitlines():
            name = " ".join(value.strip().lstrip("#").split())
            if name and name not in names:
                names.append(name)
            if len(names) >= 25:
                return tuple(names)
    return tuple(names)


def paperless_query_tag_ids(service: PaperlessDocumentService, names: tuple[str, ...]) -> tuple[int, ...]:
    if not names:
        return ()
    available = {tag.name.casefold(): tag.tag_id for tag in service.list_tags()}
    tag_ids: list[int] = []
    for name in names:
        tag_id = available.get(name.casefold())
        if tag_id and tag_id not in tag_ids:
            tag_ids.append(tag_id)
    return tuple(tag_ids)


def paperless_tag_count(query_string: str) -> int:
    return len(paperless_query_tag_names(urllib.parse.parse_qs(query_string, keep_blank_values=True)))


def document_tag_ai_token() -> str:
    if DOCUMENT_TAG_AI_TOKEN:
        return DOCUMENT_TAG_AI_TOKEN
    if DOCUMENT_TAG_AI_TOKEN_FILE:
        try:
            return Path(DOCUMENT_TAG_AI_TOKEN_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return secret_value("DOCUMENT_TAG_AI_TOKEN")


def paperless_document_tag_context(
    document_id: str,
    payload: dict[str, object],
    service: PaperlessDocumentService | None = None,
) -> tuple[dict[str, object], tuple[str, ...]]:
    active_service = service or paperless_service()
    document = active_service.get(document_id)
    available_tags = active_service.list_tags()
    title_override = " ".join(str(payload.get("title") or "").split())
    document_payload = document.as_dict()
    if title_override:
        document_payload["title"] = title_override
    context = {
        "document": {
            "id": document_payload.get("id"),
            "title": document_payload.get("title"),
            "created": document_payload.get("created"),
            "filename": document_payload.get("filename"),
            "correspondent": document_payload.get("correspondent"),
            "currentTags": document_payload.get("tags") or [],
            "contentExcerpt": str(document_payload.get("content") or "")[:4000],
        },
        "availableTags": [tag.as_dict() for tag in available_tags],
    }
    return context, tuple(tag.name for tag in available_tags)


def call_document_tag_ai(context: dict[str, object], *, urlopen=urllib.request.urlopen) -> tuple[str, ...]:
    if not DOCUMENT_TAG_AI_URL:
        raise DocumentIntakeError("paperless_tag_ai_not_configured")
    token = document_tag_ai_token()
    if not token:
        raise DocumentIntakeError("paperless_tag_ai_token_missing")
    request = urllib.request.Request(
        DOCUMENT_TAG_AI_URL,
        data=json.dumps(context, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "KaosGovernor/document-tag-ai",
        },
    )
    try:
        with urlopen(request, timeout=DOCUMENT_TAG_AI_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            code = str(body.get("error") or f"paperless_tag_ai_http_{exc.code}")
        except Exception:
            code = f"paperless_tag_ai_http_{exc.code}"
        raise DocumentIntakeError(code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DocumentIntakeError("paperless_tag_ai_request_failed") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentIntakeError("paperless_tag_ai_invalid_json") from exc
    if not isinstance(body, dict) or body.get("ok") is not True:
        error = str(body.get("error") or "paperless_tag_ai_failed") if isinstance(body, dict) else "paperless_tag_ai_invalid_response"
        raise DocumentIntakeError(error)
    raw_tags = body.get("tags") or body.get("suggestions") or []
    if not isinstance(raw_tags, list):
        raise DocumentIntakeError("paperless_tag_ai_invalid_tags")
    return paperless_metadata_tags({"tags": raw_tags})[:5]


def filter_existing_paperless_tags(tags: tuple[str, ...], available_names: tuple[str, ...]) -> tuple[str, ...]:
    available = {" ".join(name.strip().lstrip("#").split()).casefold(): name for name in available_names if name.strip()}
    selected: list[str] = []
    for tag in tags:
        normalized = " ".join(str(tag or "").strip().lstrip("#").split())
        existing = available.get(normalized.casefold())
        if existing and existing not in selected:
            selected.append(existing)
        if len(selected) >= 5:
            break
    return tuple(selected)


def paperless_tag_suggestions_payload(
    document_id: str,
    payload: dict[str, object],
    service: PaperlessDocumentService | None = None,
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    context, available_names = paperless_document_tag_context(document_id, payload, service)
    suggested = filter_existing_paperless_tags(call_document_tag_ai(context, urlopen=urlopen), available_names)
    return {
        "ok": True,
        "source": "ai",
        "document": context["document"],
        "tags": list(suggested),
        "suggestions": list(suggested),
    }


def paperless_metadata_proposal_payload(
    document_id: str,
    payload: dict[str, object],
    service: PaperlessDocumentService | None = None,
) -> dict[str, object]:
    active_service = service or paperless_service()
    title = " ".join(str(payload.get("title") or "").split())
    tags = paperless_metadata_tags(payload)
    if not title and not tags:
        raise DocumentIntakeError("paperless_metadata_required")
    proposal = active_service.metadata_proposal(document_id, title=title, tags=tags)
    return {
        "ok": True,
        "requiresConfirmation": True,
        "document": proposal["document"],
        "proposal": proposal["proposal"],
    }


def paperless_metadata_apply_payload(
    document_id: str,
    payload: dict[str, object],
    service: PaperlessDocumentService | None = None,
    store: DocumentIntakeStore | None = None,
) -> dict[str, object]:
    if payload.get("confirmed") is not True:
        raise DocumentIntakeError("paperless_confirmation_required")
    active_service = service or paperless_service()
    active_store = store or document_intake_store()
    record_id = str(payload.get("recordId") or "").strip()
    title = " ".join(str(payload.get("title") or "").split())
    tags = paperless_metadata_tags(payload)
    if not title:
        raise DocumentIntakeError("paperless_title_required")
    if record_id:
        try:
            record = active_store.get_record(record_id)
        except KeyError as exc:
            raise DocumentIntakeError("paperless_record_not_found") from exc
        if record.document_id and str(record.document_id) != str(document_id):
            raise DocumentIntakeError("paperless_record_mismatch")
    document = active_service.update_metadata(document_id, title=title, tags=tags)
    if record_id:
        active_store.update_status(record_id, status="applied", document_id=document.document_id)
    result = document.as_dict()
    result["url"] = paperless_document_url(active_service, document.document_id)
    return {"ok": True, "applied": True, "document": result}


def reconcile_paperless_inbox(
    *,
    service: PaperlessDocumentService | None = None,
    store: DocumentIntakeStore | None = None,
) -> list[object]:
    active_service = service or paperless_service()
    active_store = store or document_intake_store()
    records = [record for record in active_store.list_records() if record.status != "applied"]
    changed: list[object] = []
    for record in records:
        if record.status not in {"ocr_pending", "review"} or not record.task_id:
            continue
        try:
            task = active_service.task(record.task_id)
        except DocumentIntakeError as exc:
            if exc.code == "paperless_task_not_found":
                continue
            raise
        status_key = task.status.casefold()
        if task.success:
            document_id = task.related_document_ids[0] if task.related_document_ids else 0
            changed.append(
                active_store.update_status(
                    record.record_id,
                    status="archived" if document_id else "review",
                    document_id=document_id,
                )
            )
        elif status_key in {"failure", "revoked"}:
            changed.append(active_store.update_status(record.record_id, status="failed", error=task.status))
    return changed


def paperless_inbox_payload(
    query_string: str = "",
    service: PaperlessDocumentService | None = None,
    store: DocumentIntakeStore | None = None,
) -> dict[str, object]:
    active_service = service or paperless_service()
    active_store = store or document_intake_store()
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    refresh = (params.get("refresh") or [""])[0].strip().lower() in {"1", "true", "yes"}
    changed = reconcile_paperless_inbox(service=active_service, store=active_store) if refresh else []
    records = [record for record in active_store.list_records() if record.status != "applied"]
    pending = sum(1 for record in records if record.status == "ocr_pending")
    review = sum(1 for record in records if record.status == "review")
    return {
        "ok": True,
        "items": [paperless_inbox_item_payload(record, active_service) for record in records],
        "reconciled": len(changed),
        "counts": {
            "all": len(records),
            "pending": pending,
            "review": review,
        },
    }


def paperless_upload_payload(
    handler: BaseHTTPRequestHandler,
    *,
    service: PaperlessDocumentService | None = None,
    store: DocumentIntakeStore | None = None,
) -> dict[str, object]:
    active_service = service or paperless_service()
    active_store = store or document_intake_store()
    max_bytes = active_service.config.max_document_bytes + MAX_MULTIPART_OVERHEAD_BYTES
    fields, files = multipart_form_request(handler, max_bytes=max_bytes)
    filename, content = files.get("document") or files.get("file") or ("", b"")
    if not filename or not content:
        raise DocumentIntakeError("pdf_attachment_required")
    if not str(filename).lower().endswith(".pdf"):
        raise DocumentIntakeError("pdf_attachment_required")
    sha256 = hashlib.sha256(content).hexdigest()
    existing = active_store.find_active_by_sha(sha256)
    if existing:
        return {"ok": True, "duplicate": True, "item": existing.as_dict()}
    title = fields.get("title") or ""
    result = active_service.submit_pdf(filename, content, title=title, source="pwa")
    record = active_store.add_submitted(
        title=title or result.filename,
        filename=result.filename,
        content=content,
        task_id=result.task_id,
        source="pwa",
    )
    return {"ok": True, "duplicate": False, "item": record.as_dict(), "paperless": result.as_dict()}


def paperless_document_id(path: str) -> str:
    match = re.fullmatch(r"/api/paperless/documents/([1-9][0-9]*)", path)
    return match.group(1) if match else ""


@lru_cache(maxsize=1)
def fax_service() -> FaxService:
    return FaxService(FaxConfig.from_env())


def fax_status_for_error(exc: Exception) -> int:
    if isinstance(exc, memos_relay.MemosRelayError):
        return exc.status
    code = str(exc)
    if code in {"main_profile_required", "fax_document_not_found", "fax_job_not_found"}:
        return 404
    if code in {"fax_mode_invalid", "fax_limit_invalid", "fax_job_id_required", "fax_job_not_failed"}:
        return 400
    return 503


def _fax_query_int(params: dict[str, list[str]], name: str, default: int) -> int:
    raw = (params.get(name) or [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise FaxError(f"fax_{name}_invalid") from exc
    if value < 1 or value > 100:
        raise FaxError(f"fax_{name}_invalid")
    return value


def _fax_item_matches(item: dict[str, object], mode: str) -> bool:
    if mode == "all":
        return True
    direction = str(item.get("direction") or "").strip().lower()
    status = str(item.get("status") or "").strip().lower()
    if mode == "received":
        return direction == "incoming"
    return direction == "outgoing" and status == mode


def fax_items_payload(
    query_string: str,
    service: FaxService | None = None,
) -> dict[str, object]:
    active_service = service or fax_service()
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    mode = (params.get("mode") or ["all"])[0].strip().lower()
    if mode not in {"all", "received", "sent", "failed"}:
        raise FaxError("fax_mode_invalid")
    limit = _fax_query_int(params, "limit", 50)
    all_items = active_service.recent_items(limit=None)
    counts = {
        candidate: sum(1 for item in all_items if _fax_item_matches(item, candidate))
        for candidate in ("all", "received", "sent", "failed")
    }
    attention = {
        "failed": sum(
            1
            for item in all_items
            if _fax_item_matches(item, "failed") and not bool(item.get("attentionAcknowledged"))
        )
    }
    matching = [item for item in all_items if _fax_item_matches(item, mode)]
    items: list[dict[str, object]] = []
    for source in matching[:limit]:
        item = dict(source)
        fax_id = str(item.get("faxId") or "").strip().lower()
        item["documentUrl"] = (
            f"/api/fax/items/{fax_id}/document"
            if item.get("hasDocument") and re.fullmatch(r"[0-9a-f]{32}", fax_id)
            else ""
        )
        items.append(item)
    return {
        "ok": True,
        "mode": mode,
        "items": items,
        "counts": counts,
        "attention": attention,
        "resultCount": len(matching),
        "limit": limit,
    }


def fax_document_id(path: str) -> str:
    match = re.fullmatch(r"/api/fax/items/([0-9a-fA-F]{32})/document", path)
    return match.group(1).lower() if match else ""


def fax_acknowledge_job_id(path: str) -> str:
    match = re.fullmatch(r"/api/fax/items/([^/]+)/ack", path)
    if not match:
        return ""
    value = urllib.parse.unquote(match.group(1)).strip()
    if value in {".", ".."}:
        return ""
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value) else ""


def fax_acknowledge_payload(
    job_id: str,
    service: FaxService | None = None,
) -> dict[str, object]:
    if not job_id:
        raise FaxError("fax_job_id_required")
    result = (service or fax_service()).acknowledge_failed_job(job_id)
    return {"ok": True, **result}


def fax_document_payload(
    fax_id: str,
    service: FaxService | None = None,
) -> tuple[bytes, str]:
    document = (service or fax_service()).incoming_document_bytes(fax_id)
    content = document.get("content")
    if not isinstance(content, bytes):
        raise FaxError("fax_document_invalid")
    return content, str(document.get("filename") or "incoming-fax.pdf")


@lru_cache(maxsize=1)
def naver_mail_poller() -> NaverMailPoller:
    return NaverMailPoller(NaverMailConfig.from_env())


@lru_cache(maxsize=8)
def naver_mail_organizer(max_items: int | None = None) -> NaverMailOrganizer:
    config = MailOrganizerConfig.from_env()
    if max_items is not None:
        config = replace(config, max_items=max(5, min(50, max_items)))
    return NaverMailOrganizer(config, NaverMailConfig.from_env())


def mail_status_for_error(exc: Exception) -> int:
    if isinstance(exc, memos_relay.MemosRelayError):
        return exc.status
    code = str(exc)
    if code in {"main_profile_required", "mail_message_not_found", "mail_attachment_not_found"}:
        return 404
    if code in {
        "mail_limit_invalid",
        "mail_uid_invalid",
        "mail_mailbox_invalid",
        "mail_attachment_invalid",
        "mail_action_invalid",
        "mail_batch_empty",
        "mail_batch_invalid",
        "mail_batch_too_large",
        "mail_batch_conflict",
        "mailbox_generation_changed",
    }:
        return 400
    return 503


def _mail_query_int(params: dict[str, list[str]], name: str, default: int) -> int:
    raw = (params.get(name) or [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise NaverMailError(f"mail_{name}_invalid") from exc
    if value < 1 or value > 100:
        raise NaverMailError(f"mail_{name}_invalid")
    return value


def _mail_query_folders(params: dict[str, list[str]]) -> tuple[str, ...] | None:
    raw_values = params.get("folder") or params.get("folders") or []
    folders: list[str] = []
    for raw in raw_values:
        for part in str(raw or "").split(","):
            folder = part.strip()
            if not folder:
                continue
            if len(folder) > 160:
                raise NaverMailError("mail_mailbox_invalid")
            if folder not in folders:
                folders.append(folder)
    return tuple(folders) or None


def mail_messages_payload(
    query_string: str,
    poller: NaverMailPoller | None = None,
) -> dict[str, object]:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    limit = _mail_query_int(params, "limit", 50)
    folders = _mail_query_folders(params)
    payload = (poller or naver_mail_poller()).list_messages(limit=limit, folders=folders)
    return {
        "ok": True,
        "limit": limit,
        **payload,
    }


def mail_attention_payload(
    query_string: str,
    poller: NaverMailPoller | None = None,
) -> dict[str, object]:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    folders = _mail_query_folders(params)
    active_poller = poller or naver_mail_poller()
    status = active_poller.status()
    ok = bool(status.get("ok"))
    last_error = str(status.get("lastError") or "")
    return {
        "ok": ok,
        "pendingCount": active_poller.pending_count(folders=folders),
        "folders": list(folders or status.get("folders") or []),
        "mailboxCount": status.get("mailboxCount", 0),
        "lastScanAt": status.get("lastScanAt", ""),
        "lastError": last_error,
        "error": "" if ok else last_error or "mail_attention_unavailable",
        "enabled": status.get("enabled", False),
        "configured": status.get("configured", False),
    }


def _mail_unread_received_at(received_epoch: float) -> str:
    if received_epoch <= 0:
        return "(Unknown)"
    return datetime.fromtimestamp(received_epoch, KST).strftime("%Y-%m-%d %H:%M KST")


def _mail_message_dict(mail, *, unread: bool = False, uidvalidity: str = "") -> dict[str, object]:
    return {
        "kind": "mail",
        "direction": "incoming",
        "unread": unread,
        "mailbox": mail.mailbox,
        "uid": mail.uid,
        "uidValidity": uidvalidity,
        "sender": mail.sender,
        "subject": mail.subject,
        "preview": mail.preview,
        "receivedAt": mail.received_at,
        "attachmentCount": len(mail.attachments),
        "attachments": [
            {
                "index": index,
                "filename": attachment.filename,
                "contentType": attachment.content_type,
                "sizeBytes": len(attachment.content),
            }
            for index, attachment in enumerate(mail.attachments, start=1)
        ],
    }


def mail_unread_payload(
    query_string: str,
    organizer: NaverMailOrganizer | None = None,
) -> dict[str, object]:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    limit = _mail_query_int(params, "limit", 50)
    active_organizer = organizer or naver_mail_organizer(limit)
    entries, total = active_organizer.list_unread()
    rows = [
        {
            "kind": "mail",
            "direction": "incoming",
            "unread": True,
            "mailbox": entry.mailbox_name,
            "uid": entry.uid,
            "uidValidity": entry.uidvalidity,
            "sender": entry.sender,
            "subject": entry.subject,
            "preview": "",
            "receivedAt": _mail_unread_received_at(entry.received_epoch),
            "attachmentCount": 0,
            "attachments": [],
        }
        for entry in entries[:limit]
    ]
    return {
        "ok": True,
        "limit": limit,
        "totalUnread": total,
        "mailboxCount": len({entry.mailbox_name for entry in entries}),
        "folders": sorted({entry.mailbox_name for entry in entries}),
        "messages": rows,
    }


def mail_message_payload(
    uid: str,
    query_string: str,
    poller: NaverMailPoller | None = None,
) -> dict[str, object]:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    try:
        uid_value = int(uid)
    except (TypeError, ValueError) as exc:
        raise NaverMailError("mail_uid_invalid") from exc
    if uid_value < 1:
        raise NaverMailError("mail_uid_invalid")
    mailbox = (params.get("mailbox") or [""])[0].strip()
    if not mailbox:
        raise NaverMailError("mail_mailbox_invalid")
    mail = (poller or naver_mail_poller()).get_message(mailbox=mailbox, uid=uid_value)
    return {"ok": True, "message": _mail_message_dict(mail)}


def mail_unread_message_payload(
    uid: str,
    query_string: str,
    organizer: NaverMailOrganizer | None = None,
) -> dict[str, object]:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    try:
        uid_value = int(uid)
    except (TypeError, ValueError) as exc:
        raise MailOrganizerError("mail_uid_invalid") from exc
    if uid_value < 1:
        raise MailOrganizerError("mail_uid_invalid")
    mailbox = (params.get("mailbox") or [""])[0].strip()
    if not mailbox:
        raise MailOrganizerError("mail_mailbox_invalid")
    mail = (organizer or naver_mail_organizer()).fetch_message(mailbox_name=mailbox, uid=uid_value)
    return {"ok": True, "message": _mail_message_dict(mail, unread=True)}


def mail_attachment_payload(
    uid: str,
    attachment_index: str,
    query_string: str,
    poller: NaverMailPoller | None = None,
) -> tuple[bytes, str, str]:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    try:
        uid_value = int(uid)
        index_value = int(attachment_index)
    except (TypeError, ValueError) as exc:
        raise NaverMailError("mail_attachment_invalid") from exc
    if uid_value < 1:
        raise NaverMailError("mail_uid_invalid")
    if index_value < 1:
        raise NaverMailError("mail_attachment_invalid")
    mailbox = (params.get("mailbox") or [""])[0].strip()
    if not mailbox:
        raise NaverMailError("mail_mailbox_invalid")
    mail = (poller or naver_mail_poller()).get_message(mailbox=mailbox, uid=uid_value)
    try:
        attachment = mail.attachments[index_value - 1]
    except IndexError as exc:
        raise NaverMailError("mail_attachment_not_found") from exc
    if not attachment.content:
        raise NaverMailError("mail_attachment_not_found")
    return attachment.content, attachment.filename, attachment.content_type


def mail_unread_attachment_payload(
    uid: str,
    attachment_index: str,
    query_string: str,
    organizer: NaverMailOrganizer | None = None,
) -> tuple[bytes, str, str]:
    params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    try:
        uid_value = int(uid)
        index_value = int(attachment_index)
    except (TypeError, ValueError) as exc:
        raise MailOrganizerError("mail_attachment_invalid") from exc
    if uid_value < 1:
        raise MailOrganizerError("mail_uid_invalid")
    if index_value < 1:
        raise MailOrganizerError("mail_attachment_invalid")
    mailbox = (params.get("mailbox") or [""])[0].strip()
    if not mailbox:
        raise MailOrganizerError("mail_mailbox_invalid")
    mail = (organizer or naver_mail_organizer()).fetch_message(mailbox_name=mailbox, uid=uid_value)
    try:
        attachment = mail.attachments[index_value - 1]
    except IndexError as exc:
        raise MailOrganizerError("mail_attachment_not_found") from exc
    if not attachment.content:
        raise MailOrganizerError("mail_attachment_not_found")
    return attachment.content, attachment.filename, attachment.content_type


def mail_unread_actions_payload(
    payload: dict[str, object],
    organizer: NaverMailOrganizer | None = None,
) -> dict[str, object]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise MailOrganizerError("mail_batch_invalid")
    result = (organizer or naver_mail_organizer()).apply_unread_actions(items)
    return {"ok": True, **result}


def mail_message_uid(path: str) -> str:
    match = re.fullmatch(r"/api/mail/messages/([1-9][0-9]*)", path)
    return match.group(1) if match else ""


def mail_attachment_path(path: str) -> tuple[str, str]:
    match = re.fullmatch(r"/api/mail/messages/([1-9][0-9]*)/attachments/([1-9][0-9]*)", path)
    return (match.group(1), match.group(2)) if match else ("", "")


def mail_unread_message_uid(path: str) -> str:
    match = re.fullmatch(r"/api/mail/unread/messages/([1-9][0-9]*)", path)
    return match.group(1) if match else ""


def mail_unread_attachment_path(path: str) -> tuple[str, str]:
    match = re.fullmatch(r"/api/mail/unread/messages/([1-9][0-9]*)/attachments/([1-9][0-9]*)", path)
    return (match.group(1), match.group(2)) if match else ("", "")


def recurring_status_for_error(exc: Exception) -> int:
    message = str(exc)
    if message == "recurring_task_not_found":
        return 404
    if message in {"family_profile_required", "main_profile_required"}:
        return 404
    return 400


def recurring_task_id(path: str) -> str:
    match = re.fullmatch(r"/api/recurring-tasks/([0-9a-z-]+)", path)
    return match.group(1) if match else ""


def event_preset_id(path: str) -> str:
    match = re.fullmatch(r"/api/event-presets/([0-9a-z-]+)", path)
    return match.group(1) if match else ""


def _iso(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def recurring_task_payload(definition: RecurringTaskDefinition) -> dict[str, object]:
    return {
        "id": definition.definition_id,
        "owner": definition.owner,
        "adapterProfile": definition.adapter_profile,
        "collectionId": definition.collection_id,
        "title": definition.title,
        "memo": definition.memo,
        "firstDueDate": _iso(definition.first_due_date),
        "dueTime": definition.due_time.strftime("%H:%M"),
        "priority": definition.priority,
        "frequency": definition.frequency,
        "creationPolicy": definition.creation_policy,
        "enabled": definition.enabled,
        "shareFamily": definition.owner == "family",
        "activeUid": definition.active_uid,
        "activeCollectionId": definition.active_collection_id,
        "activeDueDate": _iso(definition.active_due_date) if definition.active_due_date else "",
        "nextDueDate": _iso(definition.next_due_date) if definition.next_due_date else "",
        "lastCompletedUid": definition.last_completed_uid,
        "lastCompletedAt": _iso(definition.last_completed_at) if definition.last_completed_at else "",
        "error": definition.last_error,
        "createdAt": _iso(definition.created_at),
        "updatedAt": _iso(definition.updated_at),
    }


class CalendarAdapterClient:
    def __init__(self, base_url: str = CALENDAR_ADAPTER_INTERNAL_URL) -> None:
        self.base_url = base_url

    def request_json(self, profile: str, method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        host = "family.kaosgdd.net" if profile == "family" else "supplies.kaosgdd.net" if profile == "supplies" else "kaosgdd.net"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Host": host,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=CALENDAR_ADAPTER_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    def bootstrap(self, profile: str) -> dict[str, object]:
        return self.request_json(profile, "GET", "/api/calendar/bootstrap")

    def list_tasks(self, profile: str) -> list[dict[str, object]]:
        payload = self.bootstrap(profile)
        return list(payload.get("tasks") or [])

    def create_task(self, profile: str, payload: dict[str, object]) -> dict[str, object]:
        return self.request_json(profile, "POST", "/api/calendar/tasks", payload)

    def update_task(self, profile: str, payload: dict[str, object]) -> dict[str, object]:
        return self.request_json(profile, "PUT", "/api/calendar/tasks", payload)

    def delete_task(self, profile: str, payload: dict[str, object]) -> dict[str, object]:
        return self.request_json(profile, "DELETE", "/api/calendar/tasks", payload)

    def mirror_custom_event_settings(self, payload: dict[str, object]) -> dict[str, object]:
        return self.request_json("main", "PUT", "/api/custom-events", payload)

    def sync_custom_events(self) -> dict[str, object]:
        return self.request_json("main", "POST", "/api/custom-events/sync", {})

    def vtodo_collection_id(self, profile: str, preferred: str = "") -> str:
        collections = self.bootstrap(profile).get("collections") or []
        if preferred:
            for collection in collections:
                if collection.get("id") == preferred and "VTODO" in (collection.get("components") or []):
                    return preferred
        for collection in collections:
            if "VTODO" in (collection.get("components") or []):
                return str(collection.get("id") or "")
        raise ValueError("no_writable_collection")


def recurring_store() -> PostgresRecurringTaskStore:
    return PostgresRecurringTaskStore(connect)


def recurring_definition_from_request(
    payload: dict[str, object],
    profile: str,
    *,
    existing: RecurringTaskDefinition | None = None,
) -> RecurringTaskDefinition:
    normalized = validate_payload(payload, family_scope=profile == "family")
    owner = existing.owner if existing else str(normalized["owner"])
    scope = "family" if owner == "family" else "personal"
    adapter_profile = "family" if owner == "family" else "main"
    collection_id = CalendarAdapterClient().vtodo_collection_id(
        adapter_profile,
        str(payload.get("collectionId") or (existing.collection_id if existing else "") or ""),
    )
    return RecurringTaskDefinition(
        definition_id=existing.definition_id if existing else str(payload.get("id") or uuid.uuid4()),
        owner=owner,
        scope=scope,
        adapter_profile=adapter_profile,
        collection_id=collection_id,
        title=str(normalized["title"]),
        memo=str(normalized["memo"]),
        first_due_date=normalized["first_due_date"],
        due_time=normalized["due_time"],
        priority=str(normalized["priority"]),
        frequency=normalized["frequency"],
        creation_policy=normalized["creation_policy"],
        enabled=bool(normalized["enabled"]),
        active_uid=existing.active_uid if existing else "",
        active_collection_id=existing.active_collection_id if existing else "",
        active_due_date=existing.active_due_date if existing else None,
        next_due_date=existing.next_due_date if existing else normalized["first_due_date"],
        last_completed_uid=existing.last_completed_uid if existing else "",
        last_completed_at=existing.last_completed_at if existing else None,
        last_error=existing.last_error if existing else "",
        created_at=existing.created_at if existing else None,
        updated_at=existing.updated_at if existing else None,
    )


def list_recurring_tasks(profile: str) -> dict[str, object]:
    return {"ok": True, "items": [recurring_task_payload(item) for item in recurring_store().list_definitions(profile)]}


def upsert_recurring_task(payload: dict[str, object], profile: str, item_id: str = "") -> dict[str, object]:
    store = recurring_store()
    existing = store.get_definition(item_id) if item_id else None
    definition = recurring_definition_from_request({**payload, "id": item_id or payload.get("id") or ""}, profile, existing=existing)
    saved = store.upsert_definition(definition)
    RecurringTaskService(store, CalendarAdapterClient()).synchronize_definition(saved, today=datetime.now().date())
    return recurring_task_payload(store.get_definition(saved.definition_id))


def delete_recurring_task(item_id: str) -> dict[str, object]:
    recurring_store().delete_definition(item_id)
    return {"ok": True, "id": item_id, "deleted": True}


def sync_recurring_tasks(profile: str) -> dict[str, object]:
    store = recurring_store()
    service = RecurringTaskService(store, CalendarAdapterClient())
    results = service.run_once(today=datetime.now().date())
    return {
        "ok": True,
        "profile": profile,
        "changed": any(plan.action != "none" or plan.clear_active for _definition_id, plan in results),
        "items": [recurring_task_payload(item) for item in store.list_definitions(profile)],
    }


def _setting_key(scope: str, name: str) -> str:
    return f"{scope}:{name}"


def _read_setting(scope: str, name: str, default: dict[str, object]) -> tuple[dict[str, object], int]:
    key = _setting_key(scope, name)
    with connect() as connection:
        row = connection.execute(
            "SELECT payload, version FROM governor_settings WHERE settings_key = %s",
            (key,),
        ).fetchone()
    if not row:
        return dict(default), 0
    payload = row[0] if isinstance(row[0], dict) else {}
    return dict(payload), int(row[1] or 0)


def _write_setting(scope: str, name: str, payload: dict[str, object]) -> tuple[dict[str, object], int]:
    key = _setting_key(scope, name)
    with connect() as connection:
        row = connection.execute(
            """
            INSERT INTO governor_settings (settings_key, settings_scope, payload)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (settings_key) DO UPDATE
            SET payload = EXCLUDED.payload, updated_at = now(), version = governor_settings.version + 1
            RETURNING payload, version
            """,
            (key, scope, json.dumps(payload, ensure_ascii=False)),
        ).fetchone()
    return dict(row[0]), int(row[1])


def _settings_scope_for_profile(profile: str) -> str:
    return "family" if profile == "family" else "personal"


def _normalize_weather_settings(payload: dict[str, object]) -> dict[str, object]:
    location = str(payload.get("location") or "pohang").strip().lower()
    if location not in WEATHER_LOCATIONS:
        raise ValueError("invalid_weather_location")
    return {"location": location}


def weather_settings_payload(profile: str) -> dict[str, object]:
    scope = _settings_scope_for_profile(profile)
    settings, version = _read_setting(scope, "weather", {"location": "pohang"})
    normalized = _normalize_weather_settings(settings)
    return {
        "ok": True,
        "profile": profile,
        "version": version,
        "settings": normalized,
        "locations": [{"id": key, "label": label} for key, label in WEATHER_LOCATIONS.items()],
    }


def _task_title(task: dict[str, object]) -> str:
    return str(task.get("title") or task.get("summary") or task.get("name") or "").strip()


def _recurring_adapter_profile(item: dict[str, object]) -> str:
    adapter_profile = str(item.get("adapterProfile") or "").strip()
    if adapter_profile:
        return adapter_profile
    return "family" if item.get("shareFamily") else "main"


def _active_recurring_task_details(recurring: list[dict[str, object]]) -> tuple[dict[tuple[str, str, str], dict[str, object]], str]:
    profiles = sorted({_recurring_adapter_profile(item) for item in recurring if item.get("activeUid")})
    if not profiles:
        return {}, ""
    tasks_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    client = CalendarAdapterClient()
    try:
        for adapter_profile in profiles:
            for task in client.list_tasks(adapter_profile):
                if not isinstance(task, dict):
                    continue
                uid = str(task.get("uid") or "").strip()
                collection = str(task.get("collection") or task.get("collectionId") or "").strip()
                if uid:
                    tasks_by_key[(adapter_profile, collection, uid)] = task
                    tasks_by_key[(adapter_profile, "", uid)] = task
    except Exception as exc:
        return {}, str(exc) or type(exc).__name__
    return tasks_by_key, ""


def _active_task_payload(item: dict[str, object], active_tasks: dict[tuple[str, str, str], dict[str, object]]) -> dict[str, object] | None:
    uid = str(item.get("activeUid") or "").strip()
    if not uid:
        return None
    key = (_recurring_adapter_profile(item), str(item.get("activeCollectionId") or "").strip(), uid)
    task = active_tasks.get(key) or active_tasks.get((key[0], "", uid))
    if not task:
        return None
    return {
        "uid": task.get("uid"),
        "collectionId": task.get("collection") or task.get("collectionId"),
        "title": _task_title(task),
        "dueDate": task.get("dueDate") or task.get("due"),
        "status": task.get("status"),
    }


def _recurring_status_item(item: dict[str, object], active_tasks: dict[tuple[str, str, str], dict[str, object]]) -> dict[str, object]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "enabled": item.get("enabled") is not False,
        "owner": item.get("owner"),
        "shareFamily": item.get("shareFamily") is True,
        "policy": item.get("creationPolicy"),
        "frequency": item.get("frequency"),
        "firstDueDate": item.get("firstDueDate"),
        "dueTime": item.get("dueTime"),
        "active": bool(item.get("activeUid")),
        "activeDueDate": item.get("activeDueDate"),
        "activeTask": _active_task_payload(item, active_tasks),
        "nextDueDate": item.get("nextDueDate"),
        "lastCompletedAt": item.get("lastCompletedAt"),
        "lastError": item.get("error"),
    }


def settings_status_payload(profile: str) -> dict[str, object]:
    generated_payload, generated_version = _read_setting("system", "generated-calendar", GeneratedCalendarSettings().as_settings_payload())
    generated_settings = GeneratedCalendarSettings.from_mapping(generated_payload)
    weather = weather_settings_payload(profile)
    presets = list_event_presets(profile)["items"]
    recurring = list_recurring_tasks(profile)["items"]
    active_tasks, active_task_error = _active_recurring_task_details(recurring)
    try:
        generated_sync = CalendarAdapterClient().request_json("main", "GET", "/api/custom-events").get("sync", {})
    except Exception as exc:
        generated_sync = {"error": str(exc) or type(exc).__name__}
    enabled_recurring = [item for item in recurring if item.get("enabled") is not False]
    on_schedule = [item for item in recurring if item.get("creationPolicy") == "on_schedule"]
    on_completion = [item for item in recurring if item.get("creationPolicy") == "on_completion"]
    return {
        "ok": True,
        "profile": profile,
        "updatedAt": _utc_now_iso(),
        "weather": {
            "version": weather["version"],
            "location": weather["settings"]["location"],
            "locationLabel": WEATHER_LOCATIONS[str(weather["settings"]["location"])],
        },
        "generatedCalendar": {
            "version": generated_version,
            "marketDaysEnabled": generated_settings.market_days_enabled,
            "claimDayEnabled": generated_settings.claim_day_enabled,
            "marketDayPolicy": "매월 5, 10, 15, 20, 25, 30일",
            "claimDayPolicy": "매주 금요일. 장날 토요일과 공휴일이면 자동 조정",
            "editable": profile == "main",
            "sync": generated_sync,
        },
        "eventPresets": {
            "count": len(presets),
            "familyCount": len([item for item in presets if item.get("owner") == "family"]),
        },
        "recurringTasks": {
            "count": len(recurring),
            "enabledCount": len(enabled_recurring),
            "onScheduleCount": len(on_schedule),
            "onCompletionCount": len(on_completion),
            "activeTaskLookupError": active_task_error,
            "items": [_recurring_status_item(item, active_tasks) for item in recurring],
        },
        "authority": {
            "settings": "KaosGovernor PostgreSQL",
            "events": "Radicale VEVENT",
            "tasks": "Radicale VTODO",
            "weather": "KaosGovernor setting + calendar adapter fetch",
        },
    }


def update_weather_settings(payload: dict[str, object], profile: str) -> dict[str, object]:
    scope = _settings_scope_for_profile(profile)
    current, _version = _read_setting(scope, "weather", {"location": "pohang"})
    normalized = _normalize_weather_settings({**current, **payload})
    saved, version = _write_setting(scope, "weather", normalized)
    return {
        "ok": True,
        "profile": profile,
        "version": version,
        "settings": _normalize_weather_settings(saved),
        "locations": [{"id": key, "label": label} for key, label in WEATHER_LOCATIONS.items()],
    }


def _event_owner(profile: str, payload: dict[str, object] | None = None, existing: dict[str, object] | None = None) -> str:
    if existing and existing.get("owner"):
        return str(existing["owner"])
    if profile == "family" or (payload or {}).get("shareFamily") is True:
        return "family"
    return "zin"


def _short_time(value: object, default: str) -> str:
    raw = str(value or "").strip() or default
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", raw):
        raw = raw[:5]
    if not re.fullmatch(r"^(?:[01]\d|2[0-3]):[0-5]\d$", raw):
        raise ValueError("invalid_time")
    return raw


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_event_preset(item: dict[str, object]) -> dict[str, object]:
    item_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or item.get("title") or "").strip()
    title = str(item.get("title") or "").strip()
    if not item_id or not name or not title:
        raise ValueError("invalid_event_preset")
    owner = str(item.get("owner") or "zin")
    if owner not in {"zin", "wife", "family"}:
        owner = "family" if item.get("shareFamily") else "zin"
    return {
        "id": item_id,
        "owner": owner,
        "name": name,
        "title": title,
        "allDay": item.get("allDay") is not False,
        "startTime": _short_time(item.get("startTime"), "09:00"),
        "endTime": _short_time(item.get("endTime"), "10:00"),
        "alarm": _short_time(item.get("alarm"), "") if str(item.get("alarm") or "").strip() else "",
        "memo": str(item.get("memo") or "").strip(),
        "shareFamily": owner == "family",
        "createdAt": str(item.get("createdAt") or _utc_now_iso()),
        "updatedAt": str(item.get("updatedAt") or _utc_now_iso()),
    }


def list_event_presets(profile: str) -> dict[str, object]:
    payload, _version = _read_setting("system", "event-presets", {"items": []})
    owner = "family" if profile == "family" else "zin"
    items = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        try:
            normalized = _normalize_event_preset(item)
        except ValueError:
            continue
        if normalized["owner"] in {owner, "family"}:
            items.append(normalized)
    items.sort(key=lambda item: (str(item.get("name", "")), str(item.get("title", "")), str(item.get("id", ""))))
    return {"ok": True, "items": items}


def upsert_event_preset(payload: dict[str, object], profile: str, item_id: str = "") -> dict[str, object]:
    store, _version = _read_setting("system", "event-presets", {"items": []})
    items = [_normalize_event_preset(item) for item in store.get("items") or [] if isinstance(item, dict)]
    target_id = item_id or str(payload.get("id") or "").strip()
    existing = next((item for item in items if item["id"] == target_id), None) if target_id else None
    if item_id and existing is None:
        raise ValueError("event_preset_not_found")
    now = _utc_now_iso()
    saved = _normalize_event_preset(
        {
            **(existing or {}),
            "id": target_id or str(uuid.uuid4()),
            "owner": _event_owner(profile, payload, existing),
            "name": payload.get("name") or payload.get("presetName") or payload.get("title") or (existing or {}).get("name") or "",
            "title": payload.get("title") or (existing or {}).get("title") or "",
            "allDay": payload.get("allDay", (existing or {}).get("allDay", True)),
            "startTime": payload.get("startTime", (existing or {}).get("startTime", "09:00")),
            "endTime": payload.get("endTime", (existing or {}).get("endTime", "10:00")),
            "alarm": payload.get("alarm", (existing or {}).get("alarm", "")),
            "memo": payload.get("memo", (existing or {}).get("memo", "")),
            "createdAt": (existing or {}).get("createdAt") or now,
            "updatedAt": now,
        }
    )
    items = [item for item in items if item["id"] != saved["id"]]
    items.append(saved)
    _write_setting("system", "event-presets", {"items": items})
    return saved


def delete_event_preset(item_id: str) -> dict[str, object]:
    store, _version = _read_setting("system", "event-presets", {"items": []})
    items = [_normalize_event_preset(item) for item in store.get("items") or [] if isinstance(item, dict)]
    kept = [item for item in items if item["id"] != item_id]
    _write_setting("system", "event-presets", {"items": kept})
    return {"ok": True, "id": item_id, "deleted": len(kept) != len(items)}


def custom_event_payload() -> dict[str, object]:
    payload, version = _read_setting("system", "generated-calendar", GeneratedCalendarSettings().as_settings_payload())
    settings = GeneratedCalendarSettings.from_mapping(payload)
    sync = CalendarAdapterClient().request_json("main", "GET", "/api/custom-events").get("sync", {})
    return {"ok": True, "version": version, "settings": settings.as_settings_payload(), "sync": sync}


def update_custom_event_settings(payload: dict[str, object]) -> dict[str, object]:
    current, _version = _read_setting("system", "generated-calendar", GeneratedCalendarSettings().as_settings_payload())
    settings = GeneratedCalendarSettings.from_mapping({**current, **payload})
    saved, version = _write_setting("system", "generated-calendar", settings.as_settings_payload())
    adapter_settings = {
        "marketDaysEnabled": bool(saved.get("marketDaysEnabled", True)),
        "claimDayEnabled": bool(saved.get("claimDayEnabled", True)),
    }
    sync = CalendarAdapterClient().mirror_custom_event_settings(adapter_settings).get("sync", {})
    return {"ok": True, "version": version, "settings": settings.as_settings_payload(), "sync": sync}


def sync_custom_events() -> dict[str, object]:
    current, version = _read_setting("system", "generated-calendar", GeneratedCalendarSettings().as_settings_payload())
    settings = GeneratedCalendarSettings.from_mapping(current)
    CalendarAdapterClient().mirror_custom_event_settings(
        {
            "marketDaysEnabled": settings.market_days_enabled,
            "claimDayEnabled": settings.claim_day_enabled,
        }
    )
    sync_response = CalendarAdapterClient().sync_custom_events()
    sync = sync_response.get("sync") or sync_response
    return {"ok": True, "version": version, "settings": settings.as_settings_payload(), "sync": sync}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            status = database_status()
            json_response(self, 200 if status.get("ok") else 503, {"ok": bool(status.get("ok")), "database": status})
            return
        if parsed.path == "/api/ledger":
            try:
                require_family_profile(self.headers)
                json_response(self, 200, ledger.list_ledger())
            except ValueError as exc:
                json_response(self, ledger_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Ledger read failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ledger_storage_unavailable"})
            return
        if parsed.path == "/api/ledger/export.xlsx":
            try:
                require_family_profile(self.headers)
                filename = f"kaos-family-ledger-{datetime.now().date().isoformat()}.xlsx"
                xlsx_response(self, ledger.workbook_bytes(), filename)
            except ValueError as exc:
                json_response(self, ledger_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Ledger export failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ledger_export_unavailable"})
            return
        if parsed.path == "/api/paperless/documents":
            try:
                require_main_access(self.headers)
                json_response(self, 200, paperless_page_payload(parsed.query))
            except (ValueError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (DocumentIntakeError, memos_relay.MemosRelayError))
                    else str(exc)
                )
                json_response(self, paperless_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Paperless browse failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "paperless_request_failed"})
            return
        if parsed.path == "/api/paperless/tags":
            try:
                require_main_access(self.headers)
                json_response(self, 200, paperless_tags_payload())
            except (ValueError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (DocumentIntakeError, memos_relay.MemosRelayError))
                    else str(exc)
                )
                json_response(self, paperless_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Paperless tags failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "paperless_tags_unavailable"})
            return
        if parsed.path == "/api/paperless/inbox":
            try:
                require_main_access(self.headers)
                json_response(self, 200, paperless_inbox_payload(parsed.query))
            except (ValueError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (DocumentIntakeError, memos_relay.MemosRelayError))
                    else str(exc)
                )
                json_response(self, paperless_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Paperless inbox failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "paperless_inbox_unavailable"})
            return
        paperless_id = paperless_document_id(parsed.path)
        if paperless_id:
            try:
                require_main_access(self.headers)
                json_response(self, 200, paperless_document_payload(paperless_id))
            except (ValueError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (DocumentIntakeError, memos_relay.MemosRelayError))
                    else str(exc)
                )
                json_response(self, paperless_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Paperless detail failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "paperless_request_failed"})
            return
        if parsed.path == "/api/fax/items":
            try:
                require_main_access(self.headers)
                json_response(self, 200, fax_items_payload(parsed.query))
            except (ValueError, FaxError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, fax_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Fax archive browse failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "fax_archive_unavailable"})
            return
        if parsed.path == "/api/supplies":
            try:
                require_main_access(self.headers)
                json_response(self, 200, supplies_payload(parsed.query))
            except (ValueError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, supply_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Supplies browse failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "supplies_unavailable"})
            return
        if parsed.path == "/api/supplies/presets":
            try:
                require_main_access(self.headers)
                json_response(self, 200, supply_presets_payload())
            except (ValueError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, supply_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Supplies presets failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "supplies_unavailable"})
            return
        if parsed.path == "/api/ai-tasks":
            try:
                require_ai_task_access(self.headers)
                json_response(self, 200, list_ai_tasks_payload(parsed.query))
            except (ValueError, AITaskError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, (AITaskError, memos_relay.MemosRelayError)) else str(exc)
                json_response(self, ai_task_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"AI task archive browse failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ai_task_archive_unavailable"})
            return
        if parsed.path == "/api/mail/attention":
            try:
                require_main_access(self.headers)
                json_response(self, 200, mail_attention_payload(parsed.query))
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Mail attention failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_attention_unavailable"})
            return
        if parsed.path == "/api/mail/messages":
            try:
                require_main_access(self.headers)
                json_response(self, 200, mail_messages_payload(parsed.query))
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Mail browse failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_archive_unavailable"})
            return
        if parsed.path == "/api/mail/unread":
            try:
                require_main_access(self.headers)
                json_response(self, 200, mail_unread_payload(parsed.query))
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Unread mail browse failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_unread_unavailable"})
            return
        unread_attachment_uid, unread_attachment_index = mail_unread_attachment_path(parsed.path)
        if unread_attachment_uid:
            try:
                require_main_access(self.headers)
                content, filename, content_type = mail_unread_attachment_payload(unread_attachment_uid, unread_attachment_index, parsed.query)
                inline_file_response(self, content, filename, content_type)
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Unread mail attachment failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_attachment_unavailable"})
            return
        unread_mail_uid = mail_unread_message_uid(parsed.path)
        if unread_mail_uid:
            try:
                require_main_access(self.headers)
                json_response(self, 200, mail_unread_message_payload(unread_mail_uid, parsed.query))
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Unread mail detail failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_detail_unavailable"})
            return
        mail_attachment_uid, mail_attachment_index = mail_attachment_path(parsed.path)
        if mail_attachment_uid:
            try:
                require_main_access(self.headers)
                content, filename, content_type = mail_attachment_payload(mail_attachment_uid, mail_attachment_index, parsed.query)
                inline_file_response(self, content, filename, content_type)
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Mail attachment failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_attachment_unavailable"})
            return
        mail_uid = mail_message_uid(parsed.path)
        if mail_uid:
            try:
                require_main_access(self.headers)
                json_response(self, 200, mail_message_payload(mail_uid, parsed.query))
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Mail detail failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_detail_unavailable"})
            return
        fax_id = fax_document_id(parsed.path)
        if fax_id:
            try:
                require_main_access(self.headers)
                content, filename = fax_document_payload(fax_id)
                inline_pdf_response(self, content, filename)
            except (ValueError, FaxError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, fax_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Fax archive document failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "fax_archive_unavailable"})
            return
        if parsed.path.startswith("/api/memos/"):
            try:
                proxy_memos(self, "GET")
            except memos_relay.MemosRelayError as exc:
                memos_relay_error(self, exc)
            return
        if parsed.path == "/api/recurring-tasks":
            try:
                json_response(self, 200, list_recurring_tasks(profile_from_headers(self.headers)))
            except (ValueError, RecurringTaskError) as exc:
                json_response(self, recurring_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Recurring task read failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "recurring_task_storage_unavailable"})
            return
        if parsed.path == "/api/event-presets":
            try:
                json_response(self, 200, list_event_presets(profile_from_headers(self.headers)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Event preset read failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "event_preset_storage_unavailable"})
            return
        if parsed.path == "/api/custom-events":
            try:
                if profile_from_headers(self.headers) != "main":
                    raise ValueError("main_profile_required")
                json_response(self, 200, custom_event_payload())
            except ValueError as exc:
                status = 404 if str(exc) == "main_profile_required" else 400
                json_response(self, status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Custom event read failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "custom_event_storage_unavailable"})
            return
        if parsed.path == "/api/weather/settings":
            try:
                json_response(self, 200, weather_settings_payload(profile_from_headers(self.headers)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Weather settings read failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "weather_settings_storage_unavailable"})
            return
        if parsed.path == "/api/settings/status":
            try:
                json_response(self, 200, settings_status_payload(profile_from_headers(self.headers)))
            except (ValueError, RecurringTaskError) as exc:
                json_response(self, recurring_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Settings status read failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "settings_status_unavailable"})
            return
        if parsed.path == "/api/system/status":
            try:
                require_main_access(self.headers)
                json_response(self, 200, system_status_payload(profile_from_headers(self.headers)))
            except (ValueError, SystemStatusError, memos_relay.MemosRelayError) as exc:
                if isinstance(exc, SystemStatusError):
                    json_response(self, exc.status, {"ok": False, "error": exc.code})
                elif isinstance(exc, memos_relay.MemosRelayError):
                    json_response(self, exc.status, {"ok": False, "error": exc.code})
                else:
                    status = 404 if str(exc) == "main_profile_required" else 400
                    json_response(self, status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"System status read failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "system_status_unavailable"})
            return
        if parsed.path == "/api/system/updates":
            try:
                require_main_access(self.headers)
                json_response(
                    self,
                    200,
                    system_updates_payload(profile_from_headers(self.headers)),
                )
            except (ValueError, SystemUpdatesError, memos_relay.MemosRelayError) as exc:
                if isinstance(exc, memos_relay.MemosRelayError):
                    json_response(self, exc.status, {"ok": False, "error": exc.code})
                else:
                    code = str(exc)
                    status = 404 if code == "main_profile_required" else 503
                    json_response(self, status, {"ok": False, "error": code})
            except Exception as exc:
                print(f"System updates read failed: {type(exc).__name__}", flush=True)
                json_response(
                    self, 503, {"ok": False, "error": "system_updates_unavailable"}
                )
            return
        json_response(self, 404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        fax_ack_id = fax_acknowledge_job_id(parsed.path)
        if fax_ack_id:
            try:
                require_main_access(self.headers)
                json_response(self, 200, fax_acknowledge_payload(fax_ack_id))
            except (ValueError, FaxError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, fax_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Fax acknowledge failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "fax_acknowledge_failed"})
            return
        if parsed.path == "/api/supplies":
            try:
                require_main_access(self.headers)
                json_response(self, 201, create_supply_payload(json_request(self)))
            except (ValueError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, supply_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Supply create failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "supply_create_failed"})
            return
        if parsed.path == "/api/supplies/presets/use":
            try:
                require_main_access(self.headers)
                payload = json_request(self)
                json_response(self, 201, create_supply_payload({"title": payload.get("name") or payload.get("title")}))
            except (ValueError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, supply_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Supply preset create failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "supply_create_failed"})
            return
        supply_uid, supply_mode = supply_state_path(parsed.path)
        if supply_uid:
            try:
                require_main_access(self.headers)
                json_response(self, 200, set_supply_state_payload(supply_uid, supply_mode))
            except (ValueError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, supply_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Supply state update failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "supply_update_failed"})
            return
        if parsed.path == "/api/mail/unread/actions":
            try:
                require_main_access(self.headers)
                json_response(self, 200, mail_unread_actions_payload(json_request(self)))
            except (ValueError, NaverMailError, MailOrganizerError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, mail_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Unread mail batch failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "mail_batch_unavailable"})
            return
        if parsed.path == "/api/paperless/documents/upload":
            try:
                require_main_access(self.headers)
                json_response(self, 201, paperless_upload_payload(self))
            except (ValueError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (DocumentIntakeError, memos_relay.MemosRelayError))
                    else str(exc)
                )
                json_response(self, paperless_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Paperless upload failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "paperless_upload_failed"})
            return
        if parsed.path == "/api/ai-tasks/run":
            try:
                require_ai_task_access(self.headers)
                json_response(self, 202, start_ai_task_request_payload(self))
            except (ValueError, AITaskError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, (AITaskError, memos_relay.MemosRelayError)) else str(exc)
                json_response(self, ai_task_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"AI task start failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ai_task_start_failed"})
            return
        if parsed.path == "/api/ai-tasks/official-doc-memo/preview":
            try:
                require_ai_task_access(self.headers)
                json_response(self, 200, preview_official_doc_memo_request_payload(self))
            except (ValueError, AITaskError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, (AITaskError, memos_relay.MemosRelayError)) else str(exc)
                json_response(self, ai_task_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Official memo AI task preview failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ai_task_preview_failed"})
            return
        if parsed.path == "/api/ai-tasks/web/preview":
            try:
                require_ai_task_access(self.headers)
                json_response(self, 200, preview_web_ai_task_payload(json_request(self)))
            except (ValueError, AITaskError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, (AITaskError, memos_relay.MemosRelayError)) else str(exc)
                json_response(self, ai_task_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Web AI task preview failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ai_task_web_preview_failed"})
            return
        if parsed.path == "/api/ai-tasks/general-web/preview":
            try:
                require_ai_task_access(self.headers)
                json_response(self, 200, preview_general_web_ai_task_payload(json_request(self)))
            except (ValueError, AITaskError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, (AITaskError, memos_relay.MemosRelayError)) else str(exc)
                json_response(self, ai_task_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"General web AI task preview failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ai_task_general_web_preview_failed"})
            return
        completed_ai_task_id = ai_task_complete_id(parsed.path)
        if completed_ai_task_id:
            try:
                require_ai_task_access(self.headers)
                json_response(self, 200, complete_ai_task_payload(completed_ai_task_id, json_request(self)))
            except (ValueError, AITaskError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, (AITaskError, memos_relay.MemosRelayError)) else str(exc)
                json_response(self, ai_task_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"AI task completion failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ai_task_complete_failed"})
            return
        paperless_tag_suggestion_id = paperless_tag_suggestion_path(parsed.path)
        if paperless_tag_suggestion_id:
            try:
                require_main_access(self.headers)
                json_response(self, 200, paperless_tag_suggestions_payload(paperless_tag_suggestion_id, json_request(self)))
            except (ValueError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (DocumentIntakeError, memos_relay.MemosRelayError))
                    else str(exc)
                )
                json_response(self, paperless_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Paperless tag suggestion failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "paperless_tag_suggestion_failed"})
            return
        paperless_id, paperless_metadata_action = paperless_metadata_path(parsed.path)
        if paperless_id:
            try:
                require_main_access(self.headers)
                payload = json_request(self)
                if paperless_metadata_action == "proposal":
                    json_response(self, 200, paperless_metadata_proposal_payload(paperless_id, payload))
                else:
                    json_response(self, 200, paperless_metadata_apply_payload(paperless_id, payload))
            except (ValueError, DocumentIntakeError, memos_relay.MemosRelayError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (DocumentIntakeError, memos_relay.MemosRelayError))
                    else str(exc)
                )
                json_response(self, paperless_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Paperless metadata failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "paperless_metadata_failed"})
            return
        if parsed.path == "/api/memos/bootstrap":
            try:
                json_response(self, 200, memos_relay.bootstrap(self.headers, json_request(self)))
            except memos_relay.MemosRelayError as exc:
                memos_relay_error(self, exc)
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        if parsed.path.startswith("/api/memos/"):
            try:
                proxy_memos(self, "POST")
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except memos_relay.MemosRelayError as exc:
                memos_relay_error(self, exc)
            return
        if parsed.path == "/api/recurring-tasks":
            try:
                json_response(self, 201, upsert_recurring_task(json_request(self), profile_from_headers(self.headers)))
            except (ValueError, RecurringTaskError) as exc:
                json_response(self, recurring_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Recurring task create failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "recurring_task_storage_unavailable"})
            return
        if parsed.path == "/api/recurring-tasks/sync":
            try:
                json_response(self, 200, sync_recurring_tasks(profile_from_headers(self.headers)))
            except (ValueError, RecurringTaskError) as exc:
                json_response(self, recurring_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Recurring task sync failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "recurring_task_sync_unavailable"})
            return
        if parsed.path == "/api/event-presets":
            try:
                json_response(self, 201, upsert_event_preset(json_request(self), profile_from_headers(self.headers)))
            except ValueError as exc:
                status = 404 if str(exc) == "event_preset_not_found" else 400
                json_response(self, status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Event preset create failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "event_preset_storage_unavailable"})
            return
        if parsed.path == "/api/custom-events/sync":
            try:
                if profile_from_headers(self.headers) != "main":
                    raise ValueError("main_profile_required")
                json_response(self, 200, sync_custom_events())
            except ValueError as exc:
                status = 404 if str(exc) == "main_profile_required" else 400
                json_response(self, status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Custom event sync failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "custom_event_sync_unavailable"})
            return
        if parsed.path == "/api/ledger/entries":
            try:
                require_family_profile(self.headers)
                json_response(self, 201, ledger.create_entry(json_request(self), request_actor(self.headers)))
            except (ValueError, ledger.LedgerConflict) as exc:
                json_response(self, ledger_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Ledger create failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ledger_storage_unavailable"})
            return
        if parsed.path == "/api/ledger/backups":
            try:
                require_family_profile(self.headers)
                json_response(self, 201, ledger.write_backup("manual"))
            except ValueError as exc:
                json_response(self, ledger_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Ledger backup failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ledger_backup_unavailable"})
            return
        json_response(self, 404, {"error": "not_found"})

    def do_PATCH(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/memos/"):
            try:
                proxy_memos(self, "PATCH")
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except memos_relay.MemosRelayError as exc:
                memos_relay_error(self, exc)
            return
        json_response(self, 404, {"error": "not_found"})

    def do_PUT(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        recurring_id = recurring_task_id(path)
        if recurring_id:
            try:
                json_response(self, 200, upsert_recurring_task(json_request(self), profile_from_headers(self.headers), recurring_id))
            except (ValueError, RecurringTaskError) as exc:
                json_response(self, recurring_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Recurring task update failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "recurring_task_storage_unavailable"})
            return
        preset_id = event_preset_id(path)
        if preset_id:
            try:
                json_response(self, 200, upsert_event_preset(json_request(self), profile_from_headers(self.headers), preset_id))
            except ValueError as exc:
                status = 404 if str(exc) == "event_preset_not_found" else 400
                json_response(self, status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Event preset update failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "event_preset_storage_unavailable"})
            return
        if path == "/api/custom-events":
            try:
                if profile_from_headers(self.headers) != "main":
                    raise ValueError("main_profile_required")
                json_response(self, 200, update_custom_event_settings(json_request(self)))
            except ValueError as exc:
                status = 404 if str(exc) == "main_profile_required" else 400
                json_response(self, status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Custom event update failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "custom_event_storage_unavailable"})
            return
        if path == "/api/weather/settings":
            try:
                json_response(self, 200, update_weather_settings(json_request(self), profile_from_headers(self.headers)))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Weather settings update failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "weather_settings_storage_unavailable"})
            return
        target_id = ledger_entry_id(path)
        if target_id:
            try:
                require_family_profile(self.headers)
                json_response(self, 200, ledger.update_entry(target_id, json_request(self), request_actor(self.headers)))
            except (ValueError, ledger.LedgerConflict) as exc:
                json_response(self, ledger_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Ledger update failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ledger_storage_unavailable"})
            return
        json_response(self, 404, {"error": "not_found"})

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        supply_uid = supply_delete_uid(parsed.path)
        if supply_uid:
            try:
                require_main_access(self.headers)
                json_response(self, 200, delete_supply_payload(supply_uid))
            except (ValueError, memos_relay.MemosRelayError) as exc:
                code = exc.code if isinstance(exc, memos_relay.MemosRelayError) else str(exc)
                json_response(self, supply_status_for_error(exc), {"ok": False, "error": code})
            except Exception as exc:
                print(f"Supply delete failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "supply_delete_failed"})
            return
        if parsed.path.startswith("/api/memos/"):
            try:
                proxy_memos(self, "DELETE")
            except memos_relay.MemosRelayError as exc:
                memos_relay_error(self, exc)
            return
        recurring_id = recurring_task_id(parsed.path)
        if recurring_id:
            try:
                json_response(self, 200, delete_recurring_task(recurring_id))
            except (ValueError, RecurringTaskError) as exc:
                json_response(self, recurring_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Recurring task delete failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "recurring_task_storage_unavailable"})
            return
        preset_id = event_preset_id(parsed.path)
        if preset_id:
            try:
                json_response(self, 200, delete_event_preset(preset_id))
            except ValueError as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Event preset delete failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "event_preset_storage_unavailable"})
            return
        target_id = ledger_entry_id(urllib.parse.urlparse(self.path).path)
        if target_id:
            try:
                require_family_profile(self.headers)
                payload = json_request(self)
                json_response(self, 200, ledger.delete_entry(target_id, payload.get("baseRevision"), request_actor(self.headers)))
            except (ValueError, ledger.LedgerConflict) as exc:
                json_response(self, ledger_status_for_error(exc), {"ok": False, "error": str(exc)})
            except Exception as exc:
                print(f"Ledger delete failed: {type(exc).__name__}", flush=True)
                json_response(self, 503, {"ok": False, "error": "ledger_storage_unavailable"})
            return
        json_response(self, 404, {"error": "not_found"})


def main() -> None:
    wait_for_database_and_migrate(MIGRATIONS)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"KaosGovernor API listening on {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
