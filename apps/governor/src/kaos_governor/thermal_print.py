from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
RECEIPT_WIDTH_MM = 80
PRINTABLE_WIDTH_MM = 70
MIN_RECEIPT_HEIGHT_MM = 65
MAX_RECEIPT_HEIGHT_MM = 2_000
MAX_BODY_CHARS = 16_000
MAX_TOTAL_CHARS = 32_000
MAX_META_ROWS = 24
MAX_SECTIONS = 64
MAX_ITEMS = 240
ALLOWED_KINDS = {"agenda", "event", "tasks", "task", "memo"}
DESTINATION_IDS = ("home", "office")
FONT_NAME = "KaosReceiptNanumGothic"
BOLD_FONT_NAME = "KaosReceiptNanumGothicBold"
FONT_CANDIDATES = (
    "/usr/local/share/kaos-governor/fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/nanum/NanumGothic.ttf",
)
BOLD_FONT_CANDIDATES = (
    "/usr/local/share/kaos-governor/fonts/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/nanum/NanumGothicBold.ttf",
)

_font_lock = threading.Lock()


class ThermalPrintError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class PrintDestination:
    id: str
    label: str
    url: str
    token: str

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)


def _clean_text(value: object, *, limit: int, required: bool = False) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        raise ThermalPrintError("invalid_print_text")
    text = text.replace("\x00", "")
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32).strip()
    if required and not text:
        raise ThermalPrintError("print_text_required")
    if len(text) > limit:
        raise ThermalPrintError("print_text_too_long")
    return text


def _normalize_meta(value: object) -> list[dict[str, str]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > MAX_META_ROWS:
        raise ThermalPrintError("invalid_print_metadata")
    result: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            raise ThermalPrintError("invalid_print_metadata")
        label = _clean_text(row.get("label"), limit=60)
        text = _clean_text(row.get("value"), limit=500)
        if label or text:
            result.append({"label": label, "value": text})
    return result


def _normalize_sections(value: object) -> list[dict[str, object]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > MAX_SECTIONS:
        raise ThermalPrintError("invalid_print_sections")
    result: list[dict[str, object]] = []
    total_items = 0
    for section in value:
        if not isinstance(section, dict):
            raise ThermalPrintError("invalid_print_sections")
        raw_items = section.get("items") or []
        if not isinstance(raw_items, list):
            raise ThermalPrintError("invalid_print_items")
        total_items += len(raw_items)
        if total_items > MAX_ITEMS:
            raise ThermalPrintError("too_many_print_items")
        items: list[dict[str, object]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                raise ThermalPrintError("invalid_print_items")
            title = _clean_text(item.get("title"), limit=500, required=True)
            detail = _clean_text(item.get("detail"), limit=2_000)
            meta = _clean_text(item.get("meta"), limit=500)
            normalized: dict[str, object] = {"title": title, "detail": detail, "meta": meta}
            if "checked" in item:
                if not isinstance(item.get("checked"), bool):
                    raise ThermalPrintError("invalid_print_item_state")
                normalized["checked"] = bool(item["checked"])
            items.append(normalized)
        result.append(
            {
                "heading": _clean_text(section.get("heading"), limit=160),
                "items": items,
            }
        )
    return result


def normalize_document(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ThermalPrintError("invalid_print_document")
    if value.get("version", 1) != 1:
        raise ThermalPrintError("unsupported_print_document")
    kind = str(value.get("kind") or "").strip().lower()
    if kind not in ALLOWED_KINDS:
        raise ThermalPrintError("invalid_print_kind")
    document: dict[str, object] = {
        "version": 1,
        "kind": kind,
        "title": _clean_text(value.get("title"), limit=300, required=True),
        "subtitle": _clean_text(value.get("subtitle"), limit=500),
        "meta": _normalize_meta(value.get("meta")),
        "sections": _normalize_sections(value.get("sections")),
        "body": _clean_text(value.get("body"), limit=MAX_BODY_CHARS),
    }
    total = len(str(document["title"])) + len(str(document["subtitle"])) + len(str(document["body"]))
    total += sum(len(row["label"]) + len(row["value"]) for row in document["meta"])  # type: ignore[index]
    total += sum(
        len(str(section["heading"]))
        + sum(len(str(item["title"])) + len(str(item["detail"])) + len(str(item["meta"])) for item in section["items"])
        for section in document["sections"]  # type: ignore[index]
    )
    if total > MAX_TOTAL_CHARS:
        raise ThermalPrintError("print_document_too_long")
    return document


def _font_path(*, bold: bool = False) -> Path:
    configured = os.environ.get(
        "THERMAL_PRINT_BOLD_FONT_PATH" if bold else "THERMAL_PRINT_FONT_PATH",
        "",
    ).strip()
    font_candidates = BOLD_FONT_CANDIDATES if bold else FONT_CANDIDATES
    candidates = (configured, *font_candidates) if configured else font_candidates
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    raise ThermalPrintError("thermal_print_font_unavailable", 503)


def _register_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    registered = pdfmetrics.getRegisteredFontNames()
    if FONT_NAME in registered and BOLD_FONT_NAME in registered:
        return FONT_NAME, BOLD_FONT_NAME
    with _font_lock:
        if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(_font_path())))
        if BOLD_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(BOLD_FONT_NAME, str(_font_path(bold=True))))
    return FONT_NAME, BOLD_FONT_NAME


def _inline_markdown(text: str) -> str:
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", text)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"<<\s*(.*?)\s*>>", r"\1", value)
    value = re.sub(r"(`{1,3}|\*\*|__|~~)", "", value)
    value = re.sub(r"(?<!\\)([*_])([^*_]+)\1", r"\2", value)
    return value.replace("\\*", "*").replace("\\_", "_").strip()


def _markdown_rows(body: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    in_code = False
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            if not in_code:
                rows.append(("space", ""))
            continue
        if not stripped:
            rows.append(("space", ""))
            continue
        if in_code:
            rows.append(("code", raw_line.rstrip()))
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            rows.append(("rule", ""))
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            rows.append(("heading", _inline_markdown(heading.group(2))))
            continue
        check = re.match(r"^[-*+]\s+\[([ xX])\]\s+(.+)$", stripped)
        if check:
            rows.append(("item", f"[{'x' if check.group(1).lower() == 'x' else ' '}] {_inline_markdown(check.group(2))}"))
            continue
        bullet = re.match(r"^[-*+]\s+(.+)$", stripped)
        if bullet:
            rows.append(("item", f"- {_inline_markdown(bullet.group(1))}"))
            continue
        quote = re.match(r"^>\s?(.*)$", stripped)
        if quote:
            rows.append(("quote", _inline_markdown(quote.group(1))))
            continue
        rows.append(("text", _inline_markdown(stripped)))
    while rows and rows[-1][0] == "space":
        rows.pop()
    return rows


def _wrap(text: str, width: float, font_name: str, size: float) -> list[str]:
    from reportlab.pdfbase import pdfmetrics

    paragraphs = str(text or "").splitlines() or [""]
    result: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            result.append("")
            continue
        remaining = paragraph
        while remaining:
            if pdfmetrics.stringWidth(remaining, font_name, size) <= width:
                result.append(remaining)
                break
            end = 1
            last_break = 0
            while end <= len(remaining) and pdfmetrics.stringWidth(remaining[:end], font_name, size) <= width:
                if remaining[end - 1].isspace():
                    last_break = end
                end += 1
            cut = last_break or max(1, end - 1)
            result.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
    return result


def _text_op(ops: list[dict[str, object]], text: str, *, size: float = 8.7, leading: float = 11.2,
             indent_mm: float = 0, before_mm: float = 0, after_mm: float = 0,
             tone: float = 0, bold: bool = False) -> None:
    if text:
        ops.append(
            {
                "type": "text",
                "text": text,
                "size": size,
                "leading": leading,
                "indentMm": indent_mm,
                "beforeMm": before_mm,
                "afterMm": after_mm,
                "tone": tone,
                "bold": bold,
            }
        )


def _append_markdown_ops(ops: list[dict[str, object]], body: str) -> None:
    for style, text in _markdown_rows(body):
        if style == "space":
            ops.append({"type": "space", "heightMm": 1.8})
        elif style == "rule":
            ops.append({"type": "rule", "beforeMm": 1.0, "afterMm": 1.0})
        elif style == "heading":
            _text_op(ops, text, size=9.7, leading=12.1, before_mm=1.3, after_mm=0.6, bold=True)
        elif style == "item":
            _text_op(ops, text, size=8.6, leading=10.9, indent_mm=2.0, after_mm=0.4)
        elif style == "quote":
            _text_op(ops, f"> {text}", size=8.4, leading=10.5, indent_mm=2.0, after_mm=0.5)
        elif style == "code":
            _text_op(ops, text, size=7.7, leading=9.5, indent_mm=2.0, after_mm=0.3)
        else:
            _text_op(ops, text, size=8.7, leading=11.1, after_mm=0.6)


def _printed_text(printed_at: datetime) -> str:
    local = printed_at.astimezone(KST)
    weekday = ("월", "화", "수", "목", "금", "토", "일")[local.weekday()]
    return f"Printed {local:%Y-%m-%d} {weekday} {local:%H:%M} KST"


def _event_document_ops(document: Mapping[str, object], printed_at: datetime) -> list[dict[str, object]]:
    ops: list[dict[str, object]] = []
    _text_op(ops, "KaosGDD", size=8.2, leading=9.8, after_mm=1.2, bold=True)
    event_line = "Event"
    if document["subtitle"]:
        event_line = f"{event_line} {document['subtitle']}"
    _text_op(ops, event_line, size=8.5, leading=10.8, after_mm=1.2, bold=True)
    ops.append({"type": "rule", "beforeMm": 1.0, "afterMm": 1.8})
    _text_op(ops, str(document["title"]), size=13.5, leading=16.3, after_mm=1.2, bold=True)
    ops.append({"type": "rule", "beforeMm": 1.0, "afterMm": 1.8})
    if document["body"]:
        _append_markdown_ops(ops, str(document["body"]))
        ops.append({"type": "rule", "beforeMm": 2.2, "afterMm": 1.5})
    _text_op(ops, _printed_text(printed_at), size=7.2, leading=8.5)
    return ops


def _document_ops(document: Mapping[str, object], printed_at: datetime) -> list[dict[str, object]]:
    if document["kind"] == "event":
        return _event_document_ops(document, printed_at)

    kind_labels = {
        "agenda": "AGENDA",
        "tasks": "TASKS",
        "task": "TASK",
        "memo": "MEMO",
    }
    ops: list[dict[str, object]] = []
    _text_op(ops, "KaosGDD", size=8.2, leading=9.8, after_mm=1.2, bold=True)
    _text_op(ops, kind_labels[str(document["kind"])], size=7.4, leading=8.8, bold=True)
    _text_op(ops, str(document["title"]), size=13.5, leading=16.3, after_mm=1.2, bold=True)
    if document["subtitle"]:
        _text_op(ops, str(document["subtitle"]), size=8.5, leading=10.8, after_mm=1.5)
    ops.append({"type": "rule", "beforeMm": 1.0, "afterMm": 1.8})

    for row in document["meta"]:  # type: ignore[union-attr]
        label = str(row["label"])
        value = str(row["value"])
        _text_op(ops, label.upper(), size=7.2, leading=8.5, bold=True)
        _text_op(ops, value, size=8.8, leading=10.8, after_mm=1.1)

    for section in document["sections"]:  # type: ignore[union-attr]
        heading = str(section["heading"])
        if heading:
            _text_op(ops, heading, size=9.5, leading=11.8, before_mm=2.2, after_mm=0.8, bold=True)
        for item in section["items"]:
            checked = item.get("checked")
            prefix = "[x] " if checked is True else "[ ] " if checked is False else "- "
            _text_op(ops, f"{prefix}{item['title']}", size=8.8, leading=11.1, indent_mm=1.0, bold=True)
            if item["meta"]:
                _text_op(ops, str(item["meta"]), size=7.4, leading=9.1, indent_mm=4.0)
            if item["detail"]:
                _text_op(ops, str(item["detail"]), size=8.1, leading=10.1, indent_mm=4.0, after_mm=1.0)

    if document["body"]:
        if document["meta"] or document["sections"]:
            ops.append({"type": "rule", "beforeMm": 1.5, "afterMm": 1.8})
        _append_markdown_ops(ops, str(document["body"]))

    ops.append({"type": "rule", "beforeMm": 2.2, "afterMm": 1.5})
    _text_op(ops, _printed_text(printed_at), size=7.2, leading=8.5)
    return ops


def render_pdf(value: object, *, now: datetime | None = None) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas

    document = normalize_document(value)
    font_name, bold_font_name = _register_fonts()
    printed_at = now or datetime.now(KST)
    ops = _document_ops(document, printed_at)
    content_width = PRINTABLE_WIDTH_MM * mm

    measured: list[dict[str, object]] = []
    height = 10 * mm
    for op in ops:
        op_type = op["type"]
        if op_type == "space":
            op_height = float(op["heightMm"]) * mm
            measured.append({**op, "height": op_height})
            height += op_height
            continue
        if op_type == "rule":
            op_height = (float(op["beforeMm"]) + float(op["afterMm"]) + 0.2) * mm
            measured.append({**op, "height": op_height})
            height += op_height
            continue
        indent = float(op["indentMm"]) * mm
        op_font_name = bold_font_name if op["bold"] else font_name
        lines = _wrap(str(op["text"]), content_width - indent, op_font_name, float(op["size"]))
        op_height = (
            float(op["beforeMm"]) * mm
            + len(lines) * float(op["leading"])
            + float(op["afterMm"]) * mm
        )
        measured.append({**op, "lines": lines, "height": op_height})
        height += op_height
    height = max(MIN_RECEIPT_HEIGHT_MM * mm, height)
    if height > MAX_RECEIPT_HEIGHT_MM * mm:
        raise ThermalPrintError("print_document_too_long")

    output = io.BytesIO()
    canvas = Canvas(output, pagesize=(RECEIPT_WIDTH_MM * mm, height), pageCompression=1)
    x = 5 * mm
    y = height - 5 * mm
    for op in measured:
        if op["type"] == "space":
            y -= float(op["height"])
            continue
        if op["type"] == "rule":
            y -= float(op["beforeMm"]) * mm
            canvas.setStrokeColorRGB(0, 0, 0)
            canvas.setLineWidth(0.45)
            canvas.line(x, y, x + content_width, y)
            y -= (float(op["afterMm"]) + 0.2) * mm
            continue
        y -= float(op["beforeMm"]) * mm
        canvas.setFillGray(float(op["tone"]))
        canvas.setFont(bold_font_name if op["bold"] else font_name, float(op["size"]))
        line_x = x + float(op["indentMm"]) * mm
        for line in op["lines"]:  # type: ignore[union-attr]
            y -= float(op["leading"])
            canvas.drawString(line_x, y, str(line))
        y -= float(op["afterMm"]) * mm
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def filename_for_document(value: object) -> str:
    document = normalize_document(value)
    raw = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", str(document["title"])).strip("-.")
    return f"{raw[:60] or document['kind']}-80mm.pdf"


def _secret_value(source: Mapping[str, str], name: str) -> str:
    direct = source.get(name, "").strip()
    path = source.get(f"{name}_FILE", "").strip()
    if direct and path:
        raise ThermalPrintError("thermal_print_secret_ambiguous", 503)
    if direct:
        return direct
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def destinations_from_env(env: Mapping[str, str] | None = None) -> list[PrintDestination]:
    source = os.environ if env is None else env
    destinations: list[PrintDestination] = []
    for destination_id in DESTINATION_IDS:
        prefix = f"THERMAL_PRINT_{destination_id.upper()}"
        url = source.get(f"{prefix}_URL", "").strip().rstrip("/")
        label_default = "Home" if destination_id == "home" else "Office"
        label = _clean_text(source.get(f"{prefix}_LABEL", label_default), limit=40, required=True)
        token = _secret_value(source, f"{prefix}_TOKEN")
        if destination_id == "home" or url:
            destinations.append(PrintDestination(destination_id, label, url, token))
    return destinations


UrlOpen = Callable[..., Any]


def _connector_request(
    destination: PrintDestination,
    path: str,
    *,
    method: str = "GET",
    payload: Mapping[str, object] | None = None,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> dict[str, object]:
    if not destination.configured:
        raise ThermalPrintError("printer_not_configured", 503)
    parsed = urllib.parse.urlparse(destination.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ThermalPrintError("invalid_printer_url", 503)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{destination.url}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {destination.token}",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    timeout = float(os.environ.get("THERMAL_PRINT_TIMEOUT_SECONDS", "10") or "10")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            error = str(json.loads(exc.read().decode("utf-8")).get("error") or "printer_request_failed")
        except Exception:
            error = "printer_request_failed"
        raise ThermalPrintError(error, 503) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ThermalPrintError("printer_unreachable", 503) from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThermalPrintError("invalid_printer_response", 502) from exc
    if not isinstance(decoded, dict):
        raise ThermalPrintError("invalid_printer_response", 502)
    return decoded


def destinations_payload(
    *,
    env: Mapping[str, str] | None = None,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> dict[str, object]:
    result: list[dict[str, object]] = []
    for destination in destinations_from_env(env):
        status = "awaiting_connection"
        available = False
        mode = ""
        if destination.url and not destination.token:
            status = "missing_token"
        elif destination.configured:
            try:
                health = _connector_request(destination, "/health", urlopen=urlopen)
                mode = str(health.get("mode") or "")
                available = bool(health.get("ready"))
                status = "ready" if available else str(health.get("status") or "printer_not_ready")
            except ThermalPrintError as exc:
                status = exc.code
        result.append(
            {
                "id": destination.id,
                "label": destination.label,
                "configured": destination.configured,
                "available": available,
                "status": status,
                "mode": mode,
            }
        )
    return {"ok": True, "previewAvailable": True, "destinations": result}


def submit_payload(
    value: object,
    *,
    env: Mapping[str, str] | None = None,
    urlopen: UrlOpen = urllib.request.urlopen,
    now: datetime | None = None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ThermalPrintError("invalid_print_request")
    destination_id = str(value.get("destinationId") or "").strip().lower()
    destinations = {item.id: item for item in destinations_from_env(env)}
    destination = destinations.get(destination_id)
    if not destination:
        raise ThermalPrintError("unknown_print_destination")
    health = _connector_request(destination, "/health", urlopen=urlopen)
    if not health.get("ready"):
        raise ThermalPrintError("printer_not_ready", 503)
    document = normalize_document(value.get("document"))
    pdf = render_pdf(document, now=now)
    job_id = uuid.uuid4().hex
    response = _connector_request(
        destination,
        "/v1/print/jobs",
        method="POST",
        payload={
            "version": 1,
            "jobId": job_id,
            "title": str(document["title"]),
            "kind": str(document["kind"]),
            "pdfSha256": hashlib.sha256(pdf).hexdigest(),
            "pdfBase64": base64.b64encode(pdf).decode("ascii"),
        },
        urlopen=urlopen,
    )
    status = str(response.get("status") or "")
    if status not in {"queued", "submitted", "printing", "printed"}:
        raise ThermalPrintError(str(response.get("error") or "printer_rejected_job"), 503)
    return {
        "ok": True,
        "jobId": str(response.get("jobId") or job_id),
        "status": status,
        "destination": {"id": destination.id, "label": destination.label},
        "printerJobId": str(response.get("printerJobId") or ""),
    }
