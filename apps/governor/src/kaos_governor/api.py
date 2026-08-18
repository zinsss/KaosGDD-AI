from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import uuid

from kaos_governor import ledger
from kaos_governor.calendar import GeneratedCalendarSettings
from kaos_governor.database import connect, database_status, wait_for_database_and_migrate
from kaos_governor.memos import relay as memos_relay
from kaos_governor.tasks import PostgresRecurringTaskStore, RecurringTaskDefinition, RecurringTaskError, RecurringTaskService, validate_payload


PORT = int(os.environ.get("GOVERNOR_API_PORT", "8096"))
MIGRATIONS = Path(os.environ.get("GOVERNOR_MIGRATIONS_DIR", "/usr/local/share/kaos-governor/migrations"))
MAX_REQUEST_BYTES = 500_000
CALENDAR_ADAPTER_INTERNAL_URL = os.environ.get("CALENDAR_ADAPTER_INTERNAL_URL", "http://calendar-adapter:8091").rstrip("/")
CALENDAR_ADAPTER_TIMEOUT_SECONDS = float(os.environ.get("CALENDAR_ADAPTER_TIMEOUT_SECONDS", "20"))


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


def profile_from_headers(headers) -> str:
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(":", 1)[0].lower()
    return "family" if host == "family.kaosgdd.net" else "main"


def require_family_profile(headers) -> None:
    if profile_from_headers(headers) != "family":
        raise ValueError("family_profile_required")


def request_actor(headers) -> str:
    return ledger.actor_name(
        headers.get("Cf-Access-Authenticated-User-Email")
        or headers.get("X-Forwarded-Email")
        or "family"
    )


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
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Host": "family.kaosgdd.net" if profile == "family" else "kaosgdd.net",
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
    sync = CalendarAdapterClient().sync_custom_events()
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
        json_response(self, 404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
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
