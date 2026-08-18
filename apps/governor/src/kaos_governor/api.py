from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kaos_governor import ledger
from kaos_governor.database import database_status, wait_for_database_and_migrate
from kaos_governor.memos import relay as memos_relay


PORT = int(os.environ.get("GOVERNOR_API_PORT", "8096"))
MIGRATIONS = Path(os.environ.get("GOVERNOR_MIGRATIONS_DIR", "/usr/local/share/kaos-governor/migrations"))
MAX_REQUEST_BYTES = 500_000


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
        target_id = ledger_entry_id(urllib.parse.urlparse(self.path).path)
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
