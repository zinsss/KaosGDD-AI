from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import Any
import urllib.parse

import discord
from kaos_governor.documents import PaperlessDocument, PaperlessSearchPage, PaperlessSearchResult

from .fax import safe_filename
from .markdown import escape_text


def rejection_message(error: Exception) -> str:
    labels = {
        "paperless_not_configured": "Paperless is not configured.",
        "pdf_attachment_required": "Only PDF attachments are accepted.",
        "pdf_size_invalid": "The PDF is empty or exceeds the configured size limit.",
        "invalid_pdf_signature": "The uploaded file is not a valid PDF.",
        "paperless_request_failed": "Paperless is not reachable.",
        "paperless_pending_missing": "This inbox item is no longer pending.",
        "paperless_source_unavailable": "The original upload is not available.",
        "paperless_attachment_missing": "The original PDF attachment is missing.",
        "paperless_attachment_changed": "The original PDF attachment changed.",
        "paperless_document_missing": "The Paperless document is no longer available.",
    }
    return labels.get(str(error), str(error))


async def read_attachment_bytes(attachment: discord.Attachment) -> bytes:
    try:
        return await attachment.read(use_cached=False)
    except discord.HTTPException:
        return await attachment.read(use_cached=True)


def attachment_display_filename(attachment: discord.Attachment) -> str:
    candidates = [
        attachment_filename_candidate(getattr(attachment, "title", "")),
        attachment_filename_candidate(getattr(attachment, "description", "")),
        attachment_filename_candidate(filename_from_url(getattr(attachment, "url", ""))),
        attachment_filename_candidate(filename_from_url(getattr(attachment, "proxy_url", ""))),
        attachment_filename_candidate(getattr(attachment, "filename", "")),
    ]
    cleaned = [safe_filename(candidate) for candidate in candidates if candidate]
    for filename in cleaned:
        if not generated_discord_filename(filename):
            return filename
    return cleaned[0] if cleaned else safe_filename(str(getattr(attachment, "filename", "") or "document.pdf"))


def attachment_filename_candidate(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    filename = safe_filename(raw)
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return filename
    if suffix:
        return ""
    return f"{filename}.pdf"


def filename_from_url(value: object) -> str:
    path = urllib.parse.urlparse(str(value or "")).path
    return urllib.parse.unquote(Path(path).name)


def generated_discord_filename(filename: str) -> bool:
    stem = Path(filename).stem
    return bool(re.fullmatch(r"[0-9a-fA-F]{12,64}", stem))


def degraded_discord_filename(filename: str) -> bool:
    stem = Path(filename).stem.strip()
    if generated_discord_filename(filename):
        return True
    if not stem:
        return True
    has_letter = any(character.isalpha() for character in stem)
    has_non_ascii = any(ord(character) > 127 for character in stem)
    return not has_non_ascii and not has_letter and bool(re.fullmatch(r"[0-9_. -]+", stem))


def infer_pdf_title(content: bytes) -> str:
    if b"%%EOF" not in content[-4096:]:
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content), strict=False)
        title = normalize_inferred_title(getattr(reader.metadata, "title", "") if reader.metadata else "")
        if title:
            return title
        if reader.pages:
            text = reader.pages[0].extract_text() or ""
            for line in text.splitlines():
                title = normalize_inferred_title(line)
                if title:
                    return title
    except Exception:
        return ""
    return ""


def normalize_inferred_title(value: object) -> str:
    title = " ".join(str(value or "").replace("\x00", " ").split())
    title = title.strip(" \t\r\n-_:;,.")
    if not title or generated_discord_filename(f"{title}.pdf"):
        return ""
    if len(title) < 2 or len(title) > 120:
        return ""
    return title


def record_display_filename(record: Any) -> str:
    if degraded_discord_filename(record.filename) and record.title and not degraded_discord_filename(f"{record.title}.pdf"):
        return safe_filename(f"{record.title}.pdf")
    return record.filename


def render_pending_message(filename: str) -> str:
    return "\n".join(
        (
            "## Documents",
            f"### {escape_text(filename)}",
            "Choose how to process this document.",
        )
    )[:1990]


def render_metadata_message(filename: str, *, reason: str = "") -> str:
    lines = [
        "## Documents",
        f"### {escape_text(filename)}",
    ]
    if reason:
        lines.append(escape_text(reason))
    lines.extend(
        (
            "Reply to this message with:",
            "```md",
            "### {title of document}",
            "#tag1 #tag2 #tag3",
            "```",
        )
    )
    return "\n".join(lines)[:1990]


def render_processing_message(filename: str) -> str:
    return "\n".join(
        (
            "## Documents",
            f"### {escape_text(filename)}",
            "- ***Paperless saved. OCR processing.***",
            "OCR and automatic document handling may take a few minutes.",
        )
    )[:1990]


def render_submitted_message(record: Any) -> str:
    lines = ["## Documents", f"### {escape_text(record.title or Path(record.filename).stem)}"]
    lines.append("- ***Paperless saved. OCR processing.***")
    if record.title:
        lines.append(f"- title: {escape_text(record.title)}")
    if record.tags:
        lines.append("- tags: " + " ".join(f"#{escape_text(tag)}" for tag in record.tags))
    return "\n".join(lines)[:1990]


def render_ocr_ready_message(record: Any, document_title: str = "") -> str:
    title = document_title or record.title or Path(record.filename).stem
    lines = [
        "## Documents",
        f"### {escape_text(title)}",
    ]
    if record.tags:
        lines.append("- " + " ".join(f"#{escape_text(tag)}" for tag in record.tags))
    if record.document_id:
        lines.append(f"- document no `{record.document_id}`")
    lines.append("- Paperless saved. OCR ready.")
    lines.append("- 수정할까요?")
    return "\n".join(lines)[:1990]


def render_ocr_done_message(record: Any) -> str:
    title = record.title or Path(record.filename).stem
    lines = [
        "## Documents",
        f"### {escape_text(title)}",
    ]
    if record.tags:
        lines.append("- " + " ".join(f"#{escape_text(tag)}" for tag in record.tags))
    if record.document_id:
        lines.append(f"- document no `{record.document_id}`")
    lines.append("- Paperless saved. OCR ready. Done.")
    return "\n".join(lines)[:1990]


def render_ocr_pending_message(record: Any) -> str:
    lines = [
        "## Documents",
        f"### {escape_text(record.title or record.filename)}",
        "- Paperless accepted the file.",
        "- OCR is still processing. Search again in a few minutes.",
    ]
    if record.task_id:
        lines.append(f"- task: `{escape_text(record.task_id)}`")
    return "\n".join(lines)[:1990]


def suggest_document_tags(document: PaperlessDocument) -> tuple[str, ...]:
    text = "\n".join(
        str(value or "")
        for value in (document.title, document.filename, document.correspondent, document.content)
        if str(value or "").strip()
    )
    tags: list[str] = []
    if re.search(r"이수|수료", text):
        tags.extend(("이수증", "수료증"))
    tags.extend(keyword_document_tags(text))
    years = re.findall(r"\b(20\d{2})\b", text)
    if not years:
        years = re.findall(r"\b(20\d{2})\b", str(document.created or ""))
    for year in years:
        tags.append(year)
    name = extract_korean_name_from_document(text)
    if name:
        tags.append(name)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


def keyword_document_tags(text: str) -> tuple[str, ...]:
    rules = (
        ("의료폐기물", "의료폐기물"),
        ("진료기록", "진료기록"),
        ("처방전", "처방전"),
        ("프린트", "프린트"),
    )
    tags: list[str] = []
    for needle, tag in rules:
        if needle in text and tag not in tags:
            tags.append(tag)
    return tuple(tags)


def extract_korean_name_from_document(text: str) -> str:
    patterns = (
        r"성\s*명\s*[:：]?\s*([가-힣]{2,5})",
        r"이\s*름\s*[:：]?\s*([가-힣]{2,5})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def merge_tags(existing: tuple[str, ...], suggested: tuple[str, ...]) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag in (*existing, *suggested):
        cleaned = str(tag or "").strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            tags.append(cleaned)
    return tuple(tags)


def render_paperless_search_summary(page: PaperlessSearchPage, *, public_url: str = "") -> str:
    if not page.query:
        return render_paperless_browse_summary(page, public_url=public_url)
    page_total = max(1, (page.result_count + page.page_size - 1) // page.page_size)
    lines = [
        "Searched..",
        f"## {escape_text(page.query or '..')}",
        f"{page.result_count} results in {page.total_count} documents",
        f"Page {page.page} / {page_total}",
    ]
    if not page.results:
        lines.append("- No matching documents.")
    else:
        lines.extend(paperless_result_line(result, public_url=public_url) for result in page.results)
    return "\n".join(lines)[:1990]


def render_paperless_opened(query: str, result: PaperlessSearchResult, *, public_url: str = "") -> str:
    lines = [f"## {'Documents search' if query else 'Documents'} · {escape_text(query or 'all')}"]
    title = escape_text(result.title or "Untitled document")
    lines.append(f"### {title}")
    link = paperless_document_link(result, public_url)
    if link:
        lines.append(f"- Open: <{link}>")
    details = []
    created = str(result.created or "")[:10]
    filename = escape_text(result.filename or "")
    correspondent = escape_text(result.correspondent or "")
    if created:
        details.append(created)
    if correspondent:
        details.append(correspondent)
    if filename:
        details.append(filename)
    if details:
        lines.append("- " + " · ".join(details))
    return "\n".join(lines)[:1990]


def render_paperless_browse_summary(page: PaperlessSearchPage, *, public_url: str = "") -> str:
    page_total = max(1, (page.result_count + page.page_size - 1) // page.page_size)
    lines = [
        "Documents..",
        "## All documents",
        f"{page.total_count} documents",
        f"Page {page.page} / {page_total}",
    ]
    if not page.results:
        lines.append("- No documents.")
    else:
        lines.extend(paperless_result_line(result, public_url=public_url) for result in page.results)
    return "\n".join(lines)[:1990]


def render_paperless_search_expired(page: PaperlessSearchPage) -> str:
    title = page.query or "all documents"
    return f"Search result of {escape_text(title)} expired."


def paperless_result_line(result: PaperlessSearchResult, *, public_url: str = "") -> str:
    title = escape_text(result.title or result.filename or f"Document {result.document_id}")
    link = paperless_document_link(result, public_url)
    suffix = f" · [open]({link})" if link else ""
    return f"- {title}{suffix}"


def render_paperless_search(query: str, results: object, *, public_url: str = "") -> str:
    normalized_results = tuple(results if isinstance(results, list | tuple) else ())
    page = PaperlessSearchPage(str(query or ""), normalized_results, len(normalized_results), len(normalized_results))
    if len(page.results) == 1:
        return render_paperless_opened(page.query, page.results[0], public_url=public_url)
    return render_paperless_search_summary(page, public_url=public_url)


def paperless_document_link(result: PaperlessSearchResult, public_url: str) -> str:
    base = public_url.rstrip("/")
    document_id = int(result.document_id or 0)
    return f"{base}/documents/{document_id}/details" if base and document_id else ""


def metadata_instruction() -> str:
    return "\n".join(
        (
            "Use this format:",
            "```md",
            "### {title of document}",
            "#tag1 #tag2 #tag3",
            "```",
        )
    )


def parse_metadata_reply(content: str) -> tuple[str, tuple[str, ...]] | None:
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    if not lines or not lines[0].startswith("### "):
        return None
    title = lines[0][4:].strip()
    if not title:
        return None
    return title, parse_tag_text("\n".join(lines[1:]))


def parse_tag_text(content: str) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    normalized = str(content or "").replace(",", " ")
    for tag in re.findall(r"#?([^\s#]+)", normalized):
        cleaned = tag.strip(".,;:!?) ]}").strip("([{")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            tags.append(cleaned)
    return tuple(tags)
