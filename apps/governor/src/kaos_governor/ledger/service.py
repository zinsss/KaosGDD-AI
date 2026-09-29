from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import io
import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from kaos_governor.database import connect


CATEGORY_DELTAS = {
    "계좌 수입": (1, 0, 0),
    "계좌 지출": (-1, 0, 0),
    "현금 인출": (-1, 1, 0),
    "계좌 입금": (1, -1, 0),
    "상품권 구입 - 계좌": (-1, 0, 1),
    "현금 수입": (0, 1, 0),
    "현금 지출": (0, -1, 0),
    "상품권 구입 - 현금": (0, -1, 1),
    "상품권 사용": (0, 0, -1),
}
CATEGORIES = tuple(CATEGORY_DELTAS)
MAX_DETAILS_LENGTH = 10_000
MAX_ACTOR_LENGTH = 254
BACKUP_ROOT = Path(os.environ.get("LEDGER_BACKUP_ROOT", "/data/ledger/backups"))
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("TZ", "Asia/Seoul"))

_backup_lock = threading.Lock()
_status_lock = threading.Lock()
_pdf_font_lock = threading.Lock()
_backup_status = {
    "enabled": True,
    "root": str(BACKUP_ROOT),
    "lastSuccessAt": "",
    "lastPath": "",
    "lastError": "",
}

PDF_ROWS_PER_PAGE = 27
_PDF_FONT_NAME = "KaosLedgerNanumGothic"
_PDF_FONT_CANDIDATES = (
    "/usr/local/share/kaos-governor/fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/nanum/NanumGothic.ttf",
)
_PDF_COLUMN_EDGES = (30.0, 109.0, 223.0, 305.0, 575.0, 654.0, 733.0, 812.0)


class LedgerConflict(Exception):
    pass


@dataclass(frozen=True)
class LedgerRepository:
    connect: Callable = connect


def local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def actor_name(value: object) -> str:
    normalized = str(value or "family").strip()
    return (normalized or "family")[:MAX_ACTOR_LENGTH]


def parse_date(value: object) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("invalid_ledger_date") from exc


def parse_amount(value: object, *, allow_empty: bool = False) -> int | None:
    if value in (None, ""):
        if allow_empty:
            return None
        raise ValueError("invalid_ledger_amount")
    if isinstance(value, bool):
        raise ValueError("invalid_ledger_amount")
    try:
        amount = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_ledger_amount") from exc
    if amount < 0:
        raise ValueError("invalid_ledger_amount")
    return amount


def normalize_details(value: object) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > MAX_DETAILS_LENGTH:
        raise ValueError("ledger_details_too_long")
    return normalized


def deltas_for(category: object, amount: object) -> tuple[str, int, tuple[int, int, int]]:
    normalized = str(category or "").strip()
    if normalized not in CATEGORY_DELTAS:
        raise ValueError("invalid_ledger_category")
    parsed_amount = parse_amount(amount)
    assert parsed_amount is not None
    factors = CATEGORY_DELTAS[normalized]
    return normalized, parsed_amount, tuple(factor * parsed_amount for factor in factors)


def normalize_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("invalid_ledger_payload")
    category, amount, deltas = deltas_for(payload.get("category"), payload.get("amount"))
    return {
        "entry_date": parse_date(payload.get("date")),
        "category": category,
        "amount": amount,
        "details": normalize_details(payload.get("details")),
        "account_delta": deltas[0],
        "cash_delta": deltas[1],
        "gift_delta": deltas[2],
    }


def _iso(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _entry_from_row(row) -> dict[str, object]:
    return {
        "id": row[0],
        "sortOrder": int(row[1]),
        "date": _iso(row[2]),
        "category": row[3],
        "amount": int(row[4]) if row[4] is not None else None,
        "details": row[5],
        "accountDelta": int(row[6]),
        "cashDelta": int(row[7]),
        "giftDelta": int(row[8]),
        "sourceRow": row[9],
        "sourceChecksum": row[10],
        "locked": bool(row[11]),
        "revision": int(row[12]),
        "createdBy": row[13],
        "updatedBy": row[14],
        "createdAt": _iso(row[15]),
        "updatedAt": _iso(row[16]),
    }


ENTRY_SELECT = """
SELECT id, sort_order, entry_date, category, amount, details,
       account_delta, cash_delta, gift_delta, source_row, source_checksum,
       locked, revision, created_by, updated_by, created_at, updated_at
FROM family_ledger_entries
WHERE deleted_at IS NULL
ORDER BY sort_order, id
"""


def _with_balances(entries: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, int]]:
    account = cash = gift = 0
    result = []
    for entry in entries:
        account += int(entry["accountDelta"])
        cash += int(entry["cashDelta"])
        gift += int(entry["giftDelta"])
        result.append({**entry, "account": account, "cash": cash, "gift": gift})
    return result, {"account": account, "cash": cash, "gift": gift}


def list_ledger(repository: LedgerRepository | None = None) -> dict[str, object]:
    repo = repository or LedgerRepository()
    with repo.connect() as connection:
        entries = [_entry_from_row(row) for row in connection.execute(ENTRY_SELECT).fetchall()]
    entries, balances = _with_balances(entries)
    return {
        "ok": True,
        "entries": entries,
        "balances": balances,
        "categories": list(CATEGORIES),
        "entryCount": len(entries),
    }


def _audit(connection, entry_id: str, action: str, actor: str, before, after) -> None:
    connection.execute(
        """
        INSERT INTO family_ledger_audit (entry_id, action, actor, before_data, after_data)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            entry_id,
            action,
            actor,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
        ),
    )


def _row_for_update(connection, entry_id: str) -> dict[str, object]:
    row = connection.execute(
        ENTRY_SELECT.replace("WHERE deleted_at IS NULL", "WHERE id = %s AND deleted_at IS NULL").replace(
            "ORDER BY sort_order, id", "FOR UPDATE"
        ),
        (entry_id,),
    ).fetchone()
    if not row:
        raise ValueError("ledger_entry_not_found")
    return _entry_from_row(row)


def _after_mutation(repository: LedgerRepository | None = None) -> None:
    try:
        write_backup("latest", repository)
    except Exception as exc:
        _set_backup_status(error=type(exc).__name__)


def create_entry(payload: object, actor: object = "family", repository: LedgerRepository | None = None) -> dict[str, object]:
    repo = repository or LedgerRepository()
    normalized = normalize_payload(payload)
    normalized_actor = actor_name(actor)
    entry_id = uuid.uuid4().hex
    with repo.connect() as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('family-ledger'))")
            sort_order = connection.execute(
                "SELECT COALESCE(max(sort_order), 0) + 1000 FROM family_ledger_entries"
            ).fetchone()[0]
            row = connection.execute(
                """
                INSERT INTO family_ledger_entries (
                    id, sort_order, entry_date, category, amount, details,
                    account_delta, cash_delta, gift_delta, created_by, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, sort_order, entry_date, category, amount, details,
                          account_delta, cash_delta, gift_delta, source_row, source_checksum,
                          locked, revision, created_by, updated_by, created_at, updated_at
                """,
                (
                    entry_id,
                    sort_order,
                    normalized["entry_date"],
                    normalized["category"],
                    normalized["amount"],
                    normalized["details"],
                    normalized["account_delta"],
                    normalized["cash_delta"],
                    normalized["gift_delta"],
                    normalized_actor,
                    normalized_actor,
                ),
            ).fetchone()
            item = _entry_from_row(row)
            _audit(connection, entry_id, "create", normalized_actor, None, item)
    _after_mutation(repo)
    return list_ledger(repo)


def update_entry(
    entry_id: str,
    payload: object,
    actor: object = "family",
    repository: LedgerRepository | None = None,
) -> dict[str, object]:
    if not re_fullmatch_ledger_id(entry_id):
        raise ValueError("ledger_entry_not_found")
    repo = repository or LedgerRepository()
    normalized = normalize_payload(payload)
    normalized_actor = actor_name(actor)
    if not isinstance(payload, dict):
        raise ValueError("invalid_ledger_payload")
    try:
        base_revision = int(payload.get("baseRevision"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_ledger_revision") from exc
    with repo.connect() as connection:
        with connection.transaction():
            before = _row_for_update(connection, entry_id)
            if before["locked"]:
                raise ValueError("ledger_entry_locked")
            if before["revision"] != base_revision:
                raise LedgerConflict("ledger_revision_conflict")
            row = connection.execute(
                """
                UPDATE family_ledger_entries
                SET entry_date = %s, category = %s, amount = %s, details = %s,
                    account_delta = %s, cash_delta = %s, gift_delta = %s,
                    revision = revision + 1, updated_by = %s, updated_at = now()
                WHERE id = %s
                RETURNING id, sort_order, entry_date, category, amount, details,
                          account_delta, cash_delta, gift_delta, source_row, source_checksum,
                          locked, revision, created_by, updated_by, created_at, updated_at
                """,
                (
                    normalized["entry_date"],
                    normalized["category"],
                    normalized["amount"],
                    normalized["details"],
                    normalized["account_delta"],
                    normalized["cash_delta"],
                    normalized["gift_delta"],
                    normalized_actor,
                    entry_id,
                ),
            ).fetchone()
            after = _entry_from_row(row)
            _audit(connection, entry_id, "update", normalized_actor, before, after)
    _after_mutation(repo)
    return list_ledger(repo)


def delete_entry(
    entry_id: str,
    base_revision: object,
    actor: object = "family",
    repository: LedgerRepository | None = None,
) -> dict[str, object]:
    if not re_fullmatch_ledger_id(entry_id):
        raise ValueError("ledger_entry_not_found")
    repo = repository or LedgerRepository()
    normalized_actor = actor_name(actor)
    try:
        revision = int(base_revision)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_ledger_revision") from exc
    with repo.connect() as connection:
        with connection.transaction():
            before = _row_for_update(connection, entry_id)
            if before["locked"]:
                raise ValueError("ledger_entry_locked")
            if before["revision"] != revision:
                raise LedgerConflict("ledger_revision_conflict")
            connection.execute(
                """
                UPDATE family_ledger_entries
                SET deleted_at = now(), revision = revision + 1,
                    updated_by = %s, updated_at = now()
                WHERE id = %s
                """,
                (normalized_actor, entry_id),
            )
            _audit(connection, entry_id, "delete", normalized_actor, before, None)
    _after_mutation(repo)
    return list_ledger(repo)


def re_fullmatch_ledger_id(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"[0-9a-z-]+", str(value or "")))


def _audit_rows(repository: LedgerRepository | None = None):
    repo = repository or LedgerRepository()
    with repo.connect() as connection:
        return connection.execute(
            """
            SELECT id, entry_id, action, actor, before_data, after_data, created_at
            FROM family_ledger_audit
            ORDER BY id
            """
        ).fetchall()


def workbook_bytes(repository: LedgerRepository | None = None) -> bytes:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    ledger = list_ledger(repository)
    workbook = Workbook()
    entries_sheet = workbook.active
    entries_sheet.title = "거래내역"
    headers = ["날짜", "사용 구분", "금액", "상세 내용", "계좌", "현금", "상품권"]
    entries_sheet.append(headers)
    for entry in ledger["entries"]:
        entries_sheet.append(
            [
                entry["date"],
                entry["category"],
                entry["amount"],
                entry["details"],
                entry["account"],
                entry["cash"],
                entry["gift"],
            ]
        )
    entries_sheet.freeze_panes = "A2"
    entries_sheet.auto_filter.ref = f"A1:G{max(1, entries_sheet.max_row)}"
    for index, width in enumerate([14, 22, 14, 48, 16, 16, 16], 1):
        entries_sheet.column_dimensions[chr(64 + index)].width = width
    for cell in entries_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="6D597A")
        cell.alignment = Alignment(horizontal="center")
    for row in entries_sheet.iter_rows(min_row=2, min_col=3, max_col=7):
        for cell in row:
            cell.number_format = '#,##0;[Red]-#,##0'

    summary_sheet = workbook.create_sheet("월별요약")
    summary_sheet.append(["월", "계좌 변동", "현금 변동", "상품권 변동", "월말 계좌", "월말 현금", "월말 상품권"])
    monthly = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for entry in ledger["entries"]:
        key = str(entry["date"])[:7]
        values = monthly[key]
        values[0] += int(entry["accountDelta"])
        values[1] += int(entry["cashDelta"])
        values[2] += int(entry["giftDelta"])
        values[3:] = [entry["account"], entry["cash"], entry["gift"]]
    for month, values in monthly.items():
        summary_sheet.append([month, *values])
    summary_sheet.freeze_panes = "A2"
    for cell in summary_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="6D597A")
    for row in summary_sheet.iter_rows(min_row=2, min_col=2, max_col=7):
        for cell in row:
            cell.number_format = '#,##0;[Red]-#,##0'
    for column in "ABCDEFG":
        summary_sheet.column_dimensions[column].width = 18

    audit_sheet = workbook.create_sheet("변경기록")
    audit_sheet.append(["번호", "시각", "작업", "사용자", "항목 ID", "변경 전", "변경 후"])
    for row in _audit_rows(repository):
        audit_sheet.append(
            [row[0], _iso(row[6]), row[2], row[3], row[1], json.dumps(row[4], ensure_ascii=False), json.dumps(row[5], ensure_ascii=False)]
        )
    audit_sheet.freeze_panes = "A2"
    for cell in audit_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="6D597A")
    for column, width in {"A": 10, "B": 24, "C": 12, "D": 28, "E": 34, "F": 80, "G": 80}.items():
        audit_sheet.column_dimensions[column].width = width

    info_sheet = workbook.create_sheet("정보")
    info_sheet.append(["항목", "값"])
    info_sheet.append(["생성 시각", local_now().isoformat()])
    info_sheet.append(["원본", "KaosGovernor PostgreSQL"])
    info_sheet.append(["거래 수", ledger["entryCount"]])
    info_sheet.append(["계좌 잔액", ledger["balances"]["account"]])
    info_sheet.append(["현금 잔액", ledger["balances"]["cash"]])
    info_sheet.append(["상품권 잔액", ledger["balances"]["gift"]])
    info_sheet["A1"].font = info_sheet["B1"].font = Font(bold=True, color="FFFFFF")
    info_sheet["A1"].fill = info_sheet["B1"].fill = PatternFill("solid", fgColor="6D597A")
    info_sheet.column_dimensions["A"].width = 18
    info_sheet.column_dimensions["B"].width = 48

    stream = io.BytesIO()
    workbook.save(stream)
    data = stream.getvalue()
    load_workbook(io.BytesIO(data), read_only=True).close()
    return data


def _ledger_pdf_font_path() -> Path:
    configured = os.environ.get("LEDGER_PDF_FONT_PATH", "").strip()
    candidates = (configured, *_PDF_FONT_CANDIDATES) if configured else _PDF_FONT_CANDIDATES
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    raise RuntimeError("ledger_pdf_font_unavailable")


def _register_ledger_pdf_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    with _pdf_font_lock:
        if _PDF_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(_PDF_FONT_NAME, str(_ledger_pdf_font_path())))
    return _PDF_FONT_NAME


def _fit_pdf_text(value: object, font_name: str, font_size: float, max_width: float) -> str:
    from reportlab.pdfbase import pdfmetrics

    text = " ".join(str(value or "").split())
    if not text or pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return text
    ellipsis = "…"
    if pdfmetrics.stringWidth(ellipsis, font_name, font_size) > max_width:
        return ""
    low = 0
    high = len(text)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = f"{text[:middle]}{ellipsis}"
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            low = middle
        else:
            high = middle - 1
    return f"{text[:low].rstrip()}{ellipsis}"


def _pdf_money(value: object, *, blank_none: bool = False) -> str:
    if value is None and blank_none:
        return ""
    return f"{int(value or 0):,}"


def pdf_bytes(repository: LedgerRepository | None = None) -> bytes:
    from reportlab.lib.colors import Color
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen.canvas import Canvas

    ledger = list_ledger(repository)
    entries = list(ledger["entries"])
    total_entries = len(entries)
    page_count = max(1, (total_entries + PDF_ROWS_PER_PAGE - 1) // PDF_ROWS_PER_PAGE)
    font_name = _register_ledger_pdf_font()
    page_width, page_height = landscape(A4)
    stream = io.BytesIO()
    document = Canvas(stream, pagesize=(page_width, page_height), pageCompression=1)
    document.setTitle("Kaos Family 거래내역")
    document.setAuthor("KaosGDD")
    document.setCreator("KaosGDD")

    title_color = Color(0.12, 0.20, 0.28)
    meta_color = Color(0.37, 0.43, 0.48)
    header_color = Color(0.15, 0.23, 0.28)
    body_color = Color(0.12, 0.16, 0.19)
    footer_color = Color(0.40, 0.45, 0.49)
    header_fill = Color(0.91, 0.94, 0.96)
    alternate_fill = Color(0.976, 0.983, 0.987)
    frame_color = Color(0.72, 0.78, 0.81)
    row_line_color = Color(0.86, 0.89, 0.91)
    table_left = _PDF_COLUMN_EDGES[0]
    table_right = _PDF_COLUMN_EDGES[-1]
    table_top = 526.0
    header_height = 24.0
    row_height = 17.0
    body_top = table_top - header_height
    headers = ("날짜", "사용 구분", "금액", "상세 내용", "계좌", "현금", "상품권")

    for page_index in range(page_count):
        start_index = page_index * PDF_ROWS_PER_PAGE
        page_entries = entries[start_index : start_index + PDF_ROWS_PER_PAGE]
        end_index = start_index + len(page_entries)
        range_label = "0건" if total_entries == 0 else f"{start_index + 1}-{end_index}건"

        document.setFillColor(title_color)
        document.setFont(font_name, 15)
        document.drawString(table_left, 548.3, "거래내역")
        document.setFillColor(meta_color)
        document.setFont(font_name, 8.5)
        document.drawRightString(table_right, 550.3, f"총 {total_entries}건 | {range_label}")

        document.setFillColor(header_fill)
        document.rect(table_left, body_top, table_right - table_left, header_height, fill=1, stroke=0)
        for row_index in range(len(page_entries)):
            if row_index % 2 == 1:
                row_bottom = body_top - ((row_index + 1) * row_height)
                document.setFillColor(alternate_fill)
                document.rect(table_left, row_bottom, table_right - table_left, row_height, fill=1, stroke=0)

        document.setStrokeColor(frame_color)
        document.setLineWidth(0.75)
        document.line(table_left, body_top, table_right, body_top)
        document.setStrokeColor(row_line_color)
        document.setLineWidth(0.55)
        for row_index in range(len(page_entries)):
            row_bottom = body_top - ((row_index + 1) * row_height)
            document.line(table_left, row_bottom, table_right, row_bottom)

        table_bottom = body_top - (len(page_entries) * row_height)
        document.setStrokeColor(frame_color)
        document.setLineWidth(0.75)
        for edge in _PDF_COLUMN_EDGES:
            document.line(edge, table_top, edge, table_bottom)

        document.setFillColor(header_color)
        document.setFont(font_name, 9)
        for column_index, header in enumerate(headers):
            document.drawString(_PDF_COLUMN_EDGES[column_index] + 6, body_top + 8.1, header)

        document.setFillColor(body_color)
        document.setFont(font_name, 8.7)
        for row_index, entry in enumerate(page_entries):
            baseline = body_top - (row_index * row_height) - 12.35
            date_text = _fit_pdf_text(entry.get("date"), font_name, 8.7, 67)
            category_text = _fit_pdf_text(entry.get("category"), font_name, 8.7, 102)
            details_text = _fit_pdf_text(entry.get("details"), font_name, 8.7, 258)
            document.drawString(_PDF_COLUMN_EDGES[0] + 6, baseline, date_text)
            document.drawString(_PDF_COLUMN_EDGES[1] + 6, baseline, category_text)
            document.drawRightString(_PDF_COLUMN_EDGES[3] - 6, baseline, _pdf_money(entry.get("amount"), blank_none=True))
            document.drawString(_PDF_COLUMN_EDGES[3] + 6, baseline, details_text)
            document.drawRightString(_PDF_COLUMN_EDGES[5] - 6, baseline, _pdf_money(entry.get("account")))
            document.drawRightString(_PDF_COLUMN_EDGES[6] - 6, baseline, _pdf_money(entry.get("cash")))
            document.drawRightString(_PDF_COLUMN_EDGES[7] - 6, baseline, _pdf_money(entry.get("gift")))

        document.setFillColor(footer_color)
        document.setFont(font_name, 8)
        document.drawString(table_left, 19.7, "Kaos Family | 거래내역")
        document.drawRightString(table_right, 19.7, f"{page_index + 1} / {page_count}")
        document.showPage()

    document.save()
    return stream.getvalue()


def _set_backup_status(*, path: str = "", error: str = "") -> None:
    with _status_lock:
        if path:
            _backup_status["lastSuccessAt"] = local_now().isoformat()
            _backup_status["lastPath"] = path
            _backup_status["lastError"] = ""
        elif error:
            _backup_status["lastError"] = error


def backup_status() -> dict[str, object]:
    with _status_lock:
        return dict(_backup_status)


def _atomic_write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    checksum = hashlib.sha256(data).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{checksum}  {path.name}\n", encoding="ascii")
    return checksum


def write_backup(kind: str = "manual", repository: LedgerRepository | None = None) -> dict[str, object]:
    now = local_now()
    with _backup_lock:
        data = workbook_bytes(repository)
        if kind == "latest":
            path = BACKUP_ROOT / "latest.xlsx"
        else:
            path = BACKUP_ROOT / "manual" / f"ledger-{now.strftime('%Y%m%d-%H%M%S')}.xlsx"
        checksum = _atomic_write(path, data)
        _set_backup_status(path=str(path))
        return {"ok": True, "path": str(path), "sha256": checksum, "size": len(data), "createdAt": now.isoformat()}
