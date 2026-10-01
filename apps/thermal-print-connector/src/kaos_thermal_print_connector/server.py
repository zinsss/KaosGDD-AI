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
ALLOWED_KINDS = {"today", "agenda", "event", "tasks", "task", "memo", "image"}
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
    output_format: str = "pdf"
    raster_dpi: int = 180
    raster_width: int = 512
    raster_threshold: int = 168
    photo_threshold: int = 128
    lp_binary: str = "lp"
    lpstat_binary: str = "lpstat"
    pdftoppm_binary: str = "pdftoppm"
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
        output_format = source.get("THERMAL_CONNECTOR_OUTPUT_FORMAT", "pdf").strip().lower()
        if output_format not in {"pdf", "escpos"}:
            raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid_output_format")
        raster_dpi = int(source.get("THERMAL_CONNECTOR_RASTER_DPI", "180") or "180")
        raster_width = int(source.get("THERMAL_CONNECTOR_RASTER_WIDTH", "512") or "512")
        raster_threshold = int(source.get("THERMAL_CONNECTOR_RASTER_THRESHOLD", "168") or "168")
        photo_threshold = int(source.get("THERMAL_CONNECTOR_PHOTO_THRESHOLD", "128") or "128")
        if (
            not 72 <= raster_dpi <= 600
            or not 64 <= raster_width <= 2_048
            or not 1 <= raster_threshold <= 254
            or not 1 <= photo_threshold <= 254
        ):
            raise ConnectorError(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid_raster_geometry")
        return cls(
            token=token,
            mode=mode,
            printer=printer,
            state_path=Path(source.get("THERMAL_CONNECTOR_STATE_PATH", "/data/connector/jobs.json")),
            output_format=output_format,
            raster_dpi=raster_dpi,
            raster_width=raster_width,
            raster_threshold=raster_threshold,
            photo_threshold=photo_threshold,
            lp_binary=source.get("THERMAL_CONNECTOR_LP", "lp").strip() or "lp",
            lpstat_binary=source.get("THERMAL_CONNECTOR_LPSTAT", "lpstat").strip() or "lpstat",
            pdftoppm_binary=source.get("THERMAL_CONNECTOR_PDFTOPPM", "pdftoppm").strip() or "pdftoppm",
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
        "outputFormat": config.output_format,
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


def _read_pgm(path: Path) -> tuple[int, int, bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed") from exc

    position = 0

    def next_token() -> bytes:
        nonlocal position
        while position < len(data):
            if data[position] in b" \t\r\n":
                position += 1
                continue
            if data[position] == ord("#"):
                newline = data.find(b"\n", position)
                if newline < 0:
                    raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
                position = newline + 1
                continue
            break
        start = position
        while position < len(data) and data[position] not in b" \t\r\n":
            position += 1
        if start == position:
            raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
        return data[start:position]

    try:
        magic = next_token()
        width = int(next_token())
        height = int(next_token())
        maximum = int(next_token())
    except (ValueError, ConnectorError) as exc:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed") from exc
    if magic != b"P5" or maximum != 255 or width <= 0 or width > 4_096 or height <= 0 or height > 65_535:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
    if position >= len(data) or data[position] not in b" \t\r\n":
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
    if data[position:position + 2] == b"\r\n":
        position += 2
    else:
        position += 1
    grayscale = data[position:]
    if len(grayscale) != width * height:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
    return width, height, grayscale


def _threshold_grayscale(width: int, height: int, grayscale: bytes, threshold: int) -> bytes:
    """Convert antialiased native-resolution grayscale into a slightly darker 1-bit raster."""
    if len(grayscale) != width * height or not 1 <= threshold <= 254:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
    row_bytes = (width + 7) // 8
    raster = bytearray(row_bytes * height)
    for y in range(height):
        source_offset = y * width
        target_offset = y * row_bytes
        for x in range(width):
            if grayscale[source_offset + x] < threshold:
                raster[target_offset + (x // 8)] |= 0x80 >> (x % 8)
    return bytes(raster)


def _dither_grayscale(width: int, height: int, grayscale: bytes, threshold: int) -> bytes:
    """Dither a native-resolution photo once, using alternating scan directions."""
    if len(grayscale) != width * height or not 1 <= threshold <= 254:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
    row_bytes = (width + 7) // 8
    raster = bytearray(row_bytes * height)
    current_error = [0] * (width + 2)
    next_error = [0] * (width + 2)
    threshold_scaled = threshold * 16
    white_scaled = 255 * 16

    for y in range(height):
        source_offset = y * width
        target_offset = y * row_bytes
        if y % 2 == 0:
            columns = range(width)
            forward = True
        else:
            columns = range(width - 1, -1, -1)
            forward = False

        for x in columns:
            value = max(
                0,
                min(white_scaled, grayscale[source_offset + x] * 16 + current_error[x + 1]),
            )
            black = value < threshold_scaled
            if black:
                raster[target_offset + (x // 8)] |= 0x80 >> (x % 8)
            error = value - (0 if black else white_scaled)
            if forward:
                current_error[x + 2] += error * 7 // 16
                next_error[x] += error * 3 // 16
                next_error[x + 1] += error * 5 // 16
                next_error[x + 2] += error // 16
            else:
                current_error[x] += error * 7 // 16
                next_error[x + 2] += error * 3 // 16
                next_error[x + 1] += error * 5 // 16
                next_error[x] += error // 16

        current_error, next_error = next_error, [0] * (width + 2)
    return bytes(raster)


def _fit_raster_width(width: int, height: int, raster: bytes, target_width: int) -> bytes:
    """Center-crop or pad 1-bit PBM rows without resampling their pixels."""
    source_row_bytes = (width + 7) // 8
    target_row_bytes = (target_width + 7) // 8
    if len(raster) != source_row_bytes * height:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
    if width == target_width:
        return raster

    source_padding = source_row_bytes * 8 - width
    target_padding = target_row_bytes * 8 - target_width
    target_mask = (1 << target_width) - 1
    result = bytearray()
    for row_index in range(height):
        start = row_index * source_row_bytes
        source_value = int.from_bytes(raster[start:start + source_row_bytes], "big") >> source_padding
        if width > target_width:
            right_crop = (width - target_width + 1) // 2
            target_value = (source_value >> right_crop) & target_mask
        else:
            right_padding = (target_width - width + 1) // 2
            target_value = source_value << right_padding
        result.extend((target_value << target_padding).to_bytes(target_row_bytes, "big"))
    return bytes(result)


def _escpos_document(
    document: Path,
    output: Path,
    config: ConnectorConfig,
    *,
    photo: bool = False,
) -> None:
    prefix = output.parent / "page"
    render = _run(
        [
            config.pdftoppm_binary,
            "-gray",
            "-r",
            str(config.raster_dpi),
            "-freetype",
            "yes",
            "-aa",
            "yes",
            "-aaVector",
            "yes",
            "-thinlinemode",
            "solid",
            str(document),
            str(prefix),
        ],
        timeout=60,
    )
    if render.returncode != 0:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")
    pages = sorted(output.parent.glob("page-*.pgm"), key=lambda path: int(path.stem.split("-")[-1]))
    if not pages:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed")

    row_bytes = (config.raster_width + 7) // 8
    result = bytearray(b"\x1b@")
    for page_index, page in enumerate(pages):
        width, height, grayscale = _read_pgm(page)
        if photo:
            source_raster = _dither_grayscale(width, height, grayscale, config.photo_threshold)
        else:
            source_raster = _threshold_grayscale(width, height, grayscale, config.raster_threshold)
        raster = _fit_raster_width(width, height, source_raster, config.raster_width)
        for top in range(0, height, 256):
            band_height = min(256, height - top)
            start = top * row_bytes
            end = start + band_height * row_bytes
            result.extend(b"\x1dv0\x00")
            result.extend((row_bytes & 0xFF, row_bytes >> 8, band_height & 0xFF, band_height >> 8))
            result.extend(raster[start:end])
        if page_index + 1 < len(pages):
            result.extend(b"\n\n")
    result.extend(b"\n\n\n\x1dV\x01")
    try:
        output.write_bytes(result)
        os.chmod(output, 0o600)
    except OSError as exc:
        raise ConnectorError(HTTPStatus.SERVICE_UNAVAILABLE, "print_render_failed") from exc


def submit_job(config: ConnectorConfig, payload: Mapping[str, Any]) -> dict[str, object]:
    kind = str(payload.get("kind") or "")
    if payload.get("version") != 1 or kind not in ALLOWED_KINDS:
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
            print_document = document
            options: list[str] = []
            if config.output_format == "escpos":
                print_document = Path(temporary) / "receipt.escpos"
                _escpos_document(document, print_document, config, photo=kind == "image")
                options = ["-o", "raw"]
            result = _run(
                [config.lp_binary, "-d", config.printer, "-t", title or "KaosGDD receipt", *options, str(print_document)],
                timeout=30,
            )
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
