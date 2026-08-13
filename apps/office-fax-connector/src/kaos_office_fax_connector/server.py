from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Mapping
from zoneinfo import ZoneInfo


UTC = ZoneInfo("UTC")
KST = ZoneInfo("Asia/Seoul")
JOB_ID = re.compile(r"^[a-f0-9]{32}$")
FAX_FILENAME = re.compile(r"fax0*([0-9]+)\.tif", re.IGNORECASE)


class ConnectorError(RuntimeError):
    def __init__(self, status: HTTPStatus, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class ConnectorConfig:
    token: str
    queue_root: Path
    recvq: Path
    xferfaxlog: Path
    doneq: Path
    state_path: Path
    max_pdf_bytes: int = 20 * 1024 * 1024
    minimum_file_age_seconds: int = 60
    tiff2pdf: str = "tiff2pdf"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ConnectorConfig":
        source = os.environ if env is None else env
        token = secret_value(source, "FAX_CONNECTOR_TOKEN")
        if not token:
            raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "connector_token_required")
        return cls(
            token=token,
            queue_root=Path(source.get("FAX_CONNECTOR_QUEUE_ROOT", "/data/fax-outgoing")),
            recvq=Path(source.get("FAX_CONNECTOR_HYLAFAX_RECVQ", "/integrations/hylafax/recvq")),
            xferfaxlog=Path(source.get("FAX_CONNECTOR_HYLAFAX_XFERFAXLOG", "/integrations/hylafax/log/xferfaxlog")),
            doneq=Path(source.get("FAX_CONNECTOR_HYLAFAX_DONEQ", "/integrations/hylafax/doneq")),
            state_path=Path(source.get("FAX_CONNECTOR_STATE_PATH", "/data/connector/state.json")),
            max_pdf_bytes=max(1, int(source.get("FAX_CONNECTOR_MAX_PDF_MB", "20"))) * 1024 * 1024,
            minimum_file_age_seconds=max(0, int(source.get("FAX_CONNECTOR_MIN_FILE_AGE_SECONDS", "60"))),
            tiff2pdf=source.get("FAX_CONNECTOR_TIFF2PDF", "tiff2pdf"),
        )


class ConnectorHandler(BaseHTTPRequestHandler):
    config: ConnectorConfig
    server_version = "KaosOfficeFaxConnector/0.1"

    def do_GET(self) -> None:
        try:
            self._require_auth()
            if self.path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            match = re.fullmatch(r"/v1/fax/jobs/([a-f0-9]{32})", self.path)
            if match:
                self._json(HTTPStatus.OK, job_status(self.config, match.group(1)))
                return
            if self.path == "/v1/fax/incoming":
                self._json(HTTPStatus.OK, {"events": incoming_events(self.config)})
                return
            raise ConnectorError(HTTPStatus.NOT_FOUND, "not_found")
        except ConnectorError as exc:
            self._json(exc.status, {"error": exc.code})

    def do_POST(self) -> None:
        try:
            self._require_auth()
            if self.path == "/v1/fax/jobs":
                self._json(HTTPStatus.ACCEPTED, submit_job(self.config, self._read_json()))
                return
            raise ConnectorError(HTTPStatus.NOT_FOUND, "not_found")
        except ConnectorError as exc:
            self._json(exc.status, {"error": exc.code})

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _require_auth(self) -> None:
        expected = f"Bearer {self.config.token}"
        if self.headers.get("Authorization") != expected:
            raise ConnectorError(HTTPStatus.UNAUTHORIZED, "unauthorized")

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_content_length") from exc
        if length <= 0 or length > self.config.max_pdf_bytes * 2:
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_request_size")
        try:
            decoded = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_json") from exc
        if not isinstance(decoded, dict):
            raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_json")
        return decoded

    def _json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def submit_job(config: ConnectorConfig, payload: Mapping[str, Any]) -> dict[str, Any]:
    job_id = str(payload.get("jobId") or "")
    if not JOB_ID.fullmatch(job_id):
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_job_id")
    filename = safe_name(str(payload.get("filename") or "fax.pdf"))
    if not filename.lower().endswith(".pdf"):
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "pdf_attachment_required")
    try:
        pdf = base64.b64decode(str(payload.get("pdfBase64") or ""), validate=True)
    except ValueError as exc:
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_pdf_base64") from exc
    if not pdf.startswith(b"%PDF-") or not pdf or len(pdf) > config.max_pdf_bytes:
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_pdf")
    job_dir = config.queue_root / "jobs" / job_id
    document = job_dir / "document.pdf"
    if not document.exists():
        atomic_bytes(document, pdf)
    manifest = {
        "version": 1,
        "jobId": job_id,
        "destination": str(payload.get("destination") or ""),
        "sender": str(payload.get("sender") or ""),
        "messageId": str(payload.get("messageId") or ""),
        "filename": filename,
        "pdfPath": f"jobs/{job_id}/document.pdf",
        "pdfSha256": str(payload.get("pdfSha256") or ""),
        "createdAt": timestamp(),
    }
    pending = config.queue_root / "pending" / f"{job_id}.json"
    processed = config.queue_root / "processed" / f"{job_id}.json"
    if not pending.exists() and not processed.exists():
        atomic_json(pending, manifest)
    status = job_status(config, job_id)
    return {"jobId": job_id, **status}


def job_status(config: ConnectorConfig, job_id: str) -> dict[str, Any]:
    if not JOB_ID.fullmatch(job_id):
        raise ConnectorError(HTTPStatus.BAD_REQUEST, "invalid_job_id")
    result = read_json(config.queue_root / "results" / f"{job_id}.json")
    if result:
        if result.get("status") == "submitted":
            hylafax_id = str(result.get("hylafaxJobId") or "")
            done = config.doneq / f"q{hylafax_id}"
            if hylafax_id and done.is_file():
                doneq = parse_doneq(done)
                return {
                    "status": "sent" if doneq["sent"] else "failed",
                    "hylafaxJobId": hylafax_id,
                    "completedAt": timestamp(done.stat().st_mtime),
                    "error": "" if doneq["sent"] else str(doneq.get("status") or "transmission_failed"),
                }
            return {"status": "submitted", "hylafaxJobId": hylafax_id}
        if result.get("status") == "failed":
            return {
                "status": "failed",
                "error": str(result.get("error") or "submission_failed"),
                "completedAt": str(result.get("completedAt") or ""),
            }
    if (config.queue_root / "pending" / f"{job_id}.json").exists():
        return {"status": "queued"}
    if (config.queue_root / "processed" / f"{job_id}.json").exists():
        return {"status": "submitted"}
    return {"status": "unknown"}


def incoming_events(config: ConnectorConfig) -> list[dict[str, Any]]:
    details = parse_xferfaxlog(config.xferfaxlog)
    now = time.time()
    events = []
    if not config.recvq.is_dir():
        return events
    for path in sorted(config.recvq.glob("fax*.tif")):
        stat = path.stat()
        if now - stat.st_mtime < config.minimum_file_age_seconds:
            continue
        match = FAX_FILENAME.fullmatch(path.name)
        if not match:
            continue
        info = details.get(f"recvq/{path.name}") or details.get(str(path)) or {}
        remote = remote_number(str(info.get("remote") or ""))
        received = received_time(str(info.get("receivedAt") or ""), path)
        filename = f"{received:%Y-%m-%d-%H:%M}_FROM_{remote}.pdf"
        events.append(
            {
                "eventId": f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}",
                "filename": filename,
                "remote": remote,
                "receivedAt": received.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "commid": str(info.get("commid") or match.group(1).zfill(9)),
                "pages": str(info.get("pages") or ""),
                "pdfBase64": base64.b64encode(tiff_to_pdf(config, path)).decode("ascii"),
            }
        )
    return events


def tiff_to_pdf(config: ConnectorConfig, source: Path) -> bytes:
    result = subprocess.run(
        [config.tiff2pdf, str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.startswith(b"%PDF-"):
        raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "tiff2pdf_failed")
    return result.stdout


def secret_value(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, f"{name.lower()}_ambiguous")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, f"{name.lower()}_file_unreadable") from exc


def timestamp(value: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if value is None else value, UTC).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(value)
    os.chmod(temporary, 0o660)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_bytes(path, json.dumps(value, indent=2, sort_keys=True).encode("utf-8"))


def safe_name(value: str) -> str:
    name = Path(str(value or "fax.pdf").replace("\\", "/")).name
    name = re.sub(r'[\x00-\x1f\x7f"\\/]+', "-", name).strip(" .-")
    return name or "fax.pdf"


def parse_doneq(path: Path) -> dict[str, Any]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        values[key.strip().lower()] = value.strip()
    status = values.get("status", "")
    return {
        **values,
        "sent": values.get("statuscode", "") == "0"
        or (values.get("state", "") == "7" and values.get("returned", "") == "2" and not status),
    }


def parse_xferfaxlog(path: Path) -> dict[str, dict[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    values = {}
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 10 or parts[1] != "RECV":
            continue
        values[parts[4].strip()] = {
            "receivedAt": parts[0].strip(),
            "commid": parts[2].strip(),
            "remote": parts[8].strip().strip('"'),
            "pages": parts[10].strip() if len(parts) > 10 else "",
        }
    return values


def remote_number(value: str) -> str:
    digits = re.sub(r"\D+", "", value)
    if digits.startswith("82") and len(digits) >= 10:
        digits = f"0{digits[2:]}"
    return digits or "unknown"


def received_time(value: str, path: Path) -> datetime:
    for pattern in ("%m/%d/%y %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=KST)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, KST)
