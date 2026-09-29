from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from typing import Any, Mapping

from pypdf import PdfReader


JOB_ID = re.compile(r"^[a-f0-9]{32}$")
SAFE_PRINTER = re.compile(r"^[A-Za-z0-9_.-]{1,127}$")
ALLOWED_KINDS = {"agenda", "event", "tasks", "task", "memo"}
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_WIDTH_POINTS = 82 / 25.4 * 72
MAX_RECEIPT_HEIGHT_POINTS = 2_050 / 25.4 * 72
_state_lock = threading.Lock()


class ConnectorError(RuntimeError):
    def __init__(self, status: HTTPStatus, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class ConnectorConfig:
    token: str
    mode: str
    printer: str
    state_path: Path
    lp_binary: str = "lp"
    lpstat_binary: str = "lpstat"
    max_pdf_bytes: int = MAX_PDF_BYTES

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ConnectorConfig":
        source = os.environ if env is None else env
        token = secret_value(source, "THERMAL_CONNECTOR_TOKEN")
        if not token:
            raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "connector_token_required")
        mode = source.get("THERMAL_CONNECTOR_MODE", "dry-run").strip().lower()
        if mode not in {"dry-run", "cups"}:
            raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid_connector_mode")
        printer = source.get("THERMAL_CONNECTOR_PRINTER", "").strip()
        if printer and not SAFE_PRINTER.fullmatch(printer):
            raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid_printer_name")
        return cls(
            token=token,
            mode=mode,
            printer=printer,
            state_path=Path(source.get("THERMAL_CONNECTOR_STATE_PATH", "/data/connector/jobs.json")),
            lp_binary=source.get("THERMAL_CONNECTOR_LP", "lp").strip() or "lp",
            lpstat_binary=source.get("THERMAL_CONNECTOR_LPSTAT", "lpstat").strip() or "lpstat",
            max_pdf_bytes=max(1, int(source.get("THERMAL_CONNECTOR_MAX_PDF_MB", "8") or "8")) * 1024 * 1024,
        )


class ConnectorHandler(BaseHTTPRequestHandler):
    config: ConnectorConfig
    server_version = "KaosThermalPrintConnector/0.1"

    def do_GET(self) -> None:
        try:
            self._require_auth()
            if self.path == "/health":
                self._json(HTTPStatus.OK, health_payload(self.config))
                return
            match = re.fullmatch(r"/v1/print/jobs/([a-f0-9]{32})", self.path)
            if match:
                self._json(HTTPStatus.OK, job_status(self.config, match.group(1)))
                return
            raise ConnectorError(HTTPStatus.NOT_FOUND, "not_found")
        except ConnectorError as exc:
            self._json(exc.status, {"error": exc.code})
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "connector_failure"})

    def do_POST(self) -> None:
        try:
            self._require_auth()
            if self.path == "/v1/print/jobs":
                self._json(HTTPStatus.ACCEPTED, submit_job(self.config, self._read_json()))
                return
            raise ConnectorError(HTTPStatus.NOT_FOUND, "not_found")
        except ConnectorError as exc:
            self._json(exc.status, {"error": exc.code})
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "connector_failure"})

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _require_auth(self) -> None:
        if self.headers.get("Authorization") != f"Bearer {self.config.token}":
            raise ConnectorError(HTTPStatus.UNAUTHORIZED, "unauthorized")

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_content_length") from exc
        if length <= 0 or length > self.config.max_pdf_bytes * 2:
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_request_size")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_json") from exc
        if not isinstance(payload, dict):
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_json")
        return payload

    def _json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def secret_value(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "connector_token_ambiguous")
    if value:
        return value
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "connector_token_unreadable") from exc


def _run(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "printer_command_failed") from exc


def printer_ready(config: ConnectorConfig) -> bool:
    if config.mode != "cups" or not config.printer:
        return False
    result = _run([config.lpstat_binary, "-p", config.printer])
    return result.returncode == 0


def health_payload(config: ConnectorConfig) -> dict[str, object]:
    ready = printer_ready(config)
    return {
        "status": "ready" if ready else "awaiting_printer" if config.mode == "dry-run" else "printer_not_ready",
        "mode": config.mode,
        "ready": ready,
        "printer": config.printer if ready else "",
    }


def _validate_pdf(payload: Mapping[str, Any], max_bytes: int) -> bytes:
    try:
        pdf = base64.b64decode(str(payload.get("pdfBase64") or ""), validate=True)
    except ValueError as exc:
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_pdf_base64") from exc
    if not pdf.startswith(b"%PDF-") or not pdf or len(pdf) > max_bytes:
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_pdf")
    expected_hash = str(payload.get("pdfSha256") or "").lower()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash) or hashlib.sha256(pdf).hexdigest() != expected_hash:
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "pdf_hash_mismatch")
    try:
        reader = PdfReader(io.BytesIO(pdf))
        if not reader.pages or len(reader.pages) > 8:
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_receipt_page_count")
        for page in reader.pages:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            if width <= 0 or width > MAX_RECEIPT_WIDTH_POINTS:
                raise ConnectorError(HTTPStatus.BAD_REQUEST, "receipt_width_required")
            if height <= 0 or height > MAX_RECEIPT_HEIGHT_POINTS:
                raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_receipt_height")
    except ConnectorError:
        raise
    except Exception as exc:
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_pdf") from exc
    return pdf


def _load_state(path: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "connector_state_invalid") from exc
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, dict):
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "connector_state_invalid")
    return jobs


def _save_state(path: Path, jobs: Mapping[str, Mapping[str, object]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "jobs": jobs}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError as exc:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "connector_state_unwritable") from exc


def submit_job(config: ConnectorConfig, payload: Mapping[str, Any]) -> dict[str, object]:
    if payload.get("version") != 1 or str(payload.get("kind") or "") not in ALLOWED_KINDS:
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_print_contract")
    job_id = str(payload.get("jobId") or "")
    if not JOB_ID.fullmatch(job_id):
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_job_id")
    title = str(payload.get("title") or "KaosGDD receipt").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()[:120]
    pdf = _validate_pdf(payload, config.max_pdf_bytes)
    with _state_lock:
        jobs = _load_state(config.state_path)
        existing = jobs.get(job_id)
        if isinstance(existing, dict):
            return dict(existing)
        if not printer_ready(config):
            raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "printer_not_ready")
        with tempfile.TemporaryDirectory(prefix="kaos-receipt-") as temporary:
            document = Path(temporary) / "receipt.pdf"
            document.write_bytes(pdf)
            result = _run([config.lp_binary, "-d", config.printer, "-t", title or "KaosGDD receipt", str(document)], timeout=30)
        if result.returncode != 0:
            raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_submission_failed")
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        match = re.search(r"request id is\s+(\S+)", output, re.IGNORECASE)
        printer_job_id = match.group(1) if match else ""
        record: dict[str, object] = {
            "jobId": job_id,
            "status": "submitted",
            "printerJobId": printer_job_id,
            "submittedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        jobs[job_id] = record
        # A bounded idempotency record is enough; receipt content is never stored.
        if len(jobs) > 1_000:
            jobs = dict(list(jobs.items())[-1_000:])
        _save_state(config.state_path, jobs)
        return record


def job_status(config: ConnectorConfig, job_id: str) -> dict[str, object]:
    if not JOB_ID.fullmatch(job_id):
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_job_id")
    with _state_lock:
        record = _load_state(config.state_path).get(job_id)
    return dict(record) if isinstance(record, dict) else {"jobId": job_id, "status": "unknown"}
