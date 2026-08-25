from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import html
from html.parser import HTMLParser
import imaplib
import json
import os
from pathlib import Path
import re
import time

KST = timezone(timedelta(hours=9), "KST")
LIST_PATTERN = re.compile(
    rb'^\((?P<flags>.*?)\)\s+(?P<delimiter>NIL|"(?:\\.|[^"])*")\s+(?P<name>.+)$'
)


class NaverMailError(RuntimeError):
    """Raised for a stable, non-secret IMAP failure code."""


@dataclass(frozen=True)
class NaverMailConfig:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    folder_roots: tuple[str, ...]
    state_path: Path
    poll_seconds: int
    timeout_seconds: float
    max_attachment_bytes: int
    preview_characters: int
    mark_existing_on_first_run: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.password and self.folder_roots)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "NaverMailConfig":
        source = os.environ if env is None else env
        roots = tuple(
            value.strip()
            for value in source.get("MAIL_NAVER_FOLDERS", "세무사,영덕군보건소").split(",")
            if value.strip()
        )
        return cls(
            enabled=_env_bool(source, "MAIL_NAVER_ENABLED"),
            host=source.get("MAIL_NAVER_HOST", "imap.naver.com").strip(),
            port=int(source.get("MAIL_NAVER_PORT", "993")),
            username=source.get("MAIL_NAVER_USERNAME", "").strip(),
            password=_env_secret(source, "MAIL_NAVER_PASSWORD"),
            folder_roots=roots,
            state_path=Path(source.get("MAIL_NAVER_STATE_PATH", "/data/mail/naver-discord.json")),
            poll_seconds=max(30, int(source.get("MAIL_NAVER_POLL_SECONDS", "60"))),
            timeout_seconds=max(1.0, float(source.get("MAIL_NAVER_TIMEOUT_SECONDS", "20"))),
            max_attachment_bytes=max(1, int(source.get("MAIL_NAVER_MAX_ATTACHMENT_MB", "20"))) * 1024 * 1024,
            preview_characters=max(200, min(3000, int(source.get("MAIL_NAVER_PREVIEW_CHARS", "2200")))),
            mark_existing_on_first_run=_env_bool(source, "MAIL_NAVER_MARK_EXISTING_ON_FIRST_RUN", True),
        )


@dataclass(frozen=True)
class Mailbox:
    raw_name: str
    display_name: str


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class MailMessage:
    mailbox: str
    uid: int
    sender: str
    subject: str
    preview: str
    attachments: tuple[Attachment, ...]
    received_at: str


@dataclass
class MailRuntimeStatus:
    started: bool = False
    last_scan_at: str = ""
    last_archive_at: str = ""
    last_error: str = ""
    archived_count: int = 0
    mailbox_count: int = 0


class TextExtractor(HTMLParser):
    blocks = {"address", "article", "blockquote", "br", "div", "h1", "h2", "h3", "h4", "li", "p", "pre", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "head"}:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self.blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self.blocks:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _env_bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_secret(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise ValueError(f"set either {name} or {name}_FILE, not both")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"unable to read {name}_FILE") from exc


def encode_modified_utf7(value: str) -> str:
    result: list[str] = []
    buffered: list[str] = []

    def flush() -> None:
        if buffered:
            encoded = base64.b64encode("".join(buffered).encode("utf-16be")).decode("ascii")
            result.append("&" + encoded.rstrip("=").replace("/", ",") + "-")
            buffered.clear()

    for character in value:
        if 0x20 <= ord(character) <= 0x7E:
            flush()
            result.append("&-" if character == "&" else character)
        else:
            buffered.append(character)
    flush()
    return "".join(result)


def decode_modified_utf7(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "&":
            end = value.find("&", index)
            end = len(value) if end < 0 else end
            result.append(value[index:end])
            index = end
            continue
        end = value.find("-", index)
        if end < 0:
            result.append(value[index:])
            break
        encoded = value[index + 1 : end]
        if not encoded:
            result.append("&")
        else:
            encoded = encoded.replace(",", "/")
            encoded += "=" * ((4 - len(encoded) % 4) % 4)
            result.append(base64.b64decode(encoded).decode("utf-16be"))
        index = end + 1
    return "".join(result)


def unquote_imap(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace(r'\"', '"').replace(r"\\", "\\")
    return value


def quoted_mailbox(raw_name: str) -> str:
    return '"' + raw_name.replace("\\", "\\\\").replace('"', r'\"') + '"'


def parse_list_line(line: bytes | str) -> tuple[str, Mailbox] | None:
    raw = line if isinstance(line, bytes) else str(line).encode("ascii", errors="replace")
    match = LIST_PATTERN.match(raw)
    if not match:
        return None
    delimiter = unquote_imap(match.group("delimiter").decode("ascii", errors="replace"))
    delimiter = "" if delimiter == "NIL" else delimiter
    raw_name = unquote_imap(match.group("name").decode("ascii", errors="replace"))
    return delimiter, Mailbox(raw_name, decode_modified_utf7(raw_name))


def discover_mailboxes(client: imaplib.IMAP4_SSL, roots: tuple[str, ...]) -> list[Mailbox]:
    status, rows = client.list()
    if status != "OK":
        raise NaverMailError("imap_list_failed")
    found: list[Mailbox] = []
    for row in rows or []:
        parsed = parse_list_line(row)
        if not parsed:
            continue
        delimiter, mailbox = parsed
        if any(_mailbox_matches_root(mailbox.display_name, root, delimiter) for root in roots):
            found.append(mailbox)
    return sorted(found, key=lambda item: item.display_name)


def _mailbox_matches_root(display_name: str, root: str, delimiter: str) -> bool:
    if display_name == root or (delimiter and display_name.startswith(f"{root}{delimiter}")):
        return True
    if not delimiter:
        return False
    return root in [part for part in display_name.split(delimiter) if part]


def format_sender(value: object) -> str:
    raw = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    formatted: list[str] = []
    for name, address in getaddresses([raw]):
        name = name.replace(r'\"', '"').strip().strip('"').strip()
        address = address.strip()
        formatted.append(f"{name} <{address}>" if name and address else address or name)
    return ", ".join(item for item in formatted if item) or raw.replace(r'\"', '"').strip('"').strip() or "Unknown sender"


def normalize_text(value: str) -> str:
    lines: list[str] = []
    blank = False
    for raw_line in html.unescape(value).replace("\r", "").split("\n"):
        line = re.sub(r"[\t ]+", " ", raw_line).strip()
        if line:
            lines.append(line)
            blank = False
        elif lines and not blank:
            lines.append("")
            blank = True
    return "\n".join(lines).strip()


def html_to_text(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value)
    parser.close()
    return normalize_text("".join(parser.parts))


def format_received_at(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "(Unknown)"
    try:
        received_at = parsedate_to_datetime(raw)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        return received_at.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    except (AttributeError, TypeError, ValueError, OverflowError):
        return " ".join(raw.split())[:128] or "(Unknown)"


def parse_message(raw: bytes, mailbox: str, uid: int, preview_characters: int = 2200) -> MailMessage:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[Attachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = str(part.get_filename() or "").strip()
        disposition = part.get_content_disposition()
        payload = part.get_payload(decode=True) or b""
        if filename or disposition == "attachment":
            attachments.append(Attachment(filename or "attachment", part.get_content_type(), payload))
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError):
            content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if isinstance(content, str) and part.get_content_type() == "text/plain":
            plain_parts.append(content)
        elif isinstance(content, str) and part.get_content_type() == "text/html":
            html_parts.append(content)
    body = normalize_text("\n\n".join(plain_parts))
    if not body and html_parts:
        body = html_to_text("\n".join(html_parts))
    return MailMessage(
        mailbox=mailbox,
        uid=uid,
        sender=format_sender(message.get("from", "")),
        subject=str(message.get("subject", "")).strip() or "(No subject)",
        preview=body[:preview_characters],
        attachments=tuple(attachments),
        received_at=format_received_at(message.get("date", "")),
    )


class NaverMailPoller:
    def __init__(self, config: NaverMailConfig, imap_factory=None) -> None:
        self.config = config
        self.imap_factory = imap_factory or imaplib.IMAP4_SSL
        self.runtime = MailRuntimeStatus()

    def load_state(self) -> dict[str, object]:
        try:
            payload = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"mailboxes": {}}
        mailboxes = payload.get("mailboxes") if isinstance(payload, dict) else None
        return {"mailboxes": mailboxes if isinstance(mailboxes, dict) else {}}

    def save_state(self, state: dict[str, object]) -> None:
        path = self.config.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

    def status(self) -> dict[str, object]:
        runtime = self.runtime
        return {
            "ok": (not self.config.enabled) or (self.config.configured and not runtime.last_error),
            "enabled": self.config.enabled,
            "configured": self.config.configured,
            "started": runtime.started,
            "folders": list(self.config.folder_roots),
            "statePath": str(self.config.state_path),
            "pollSeconds": self.config.poll_seconds,
            "lastScanAt": runtime.last_scan_at,
            "lastArchiveAt": runtime.last_archive_at,
            "lastError": runtime.last_error,
            "archivedCount": runtime.archived_count,
            "mailboxCount": runtime.mailbox_count,
        }

    def scan(
        self,
        summary_sender: Callable[[MailMessage], object],
        attachment_sender: Callable[[Attachment], object],
    ) -> int:
        self.runtime.started = True
        state = self.load_state()

        def persist() -> None:
            self.save_state(state)

        try:
            archived, mailbox_count = self._poll(
                state,
                summary_sender=summary_sender,
                attachment_sender=attachment_sender,
                persist=persist,
            )
            self.save_state(state)
            self.runtime.last_scan_at = _utc_timestamp()
            self.runtime.last_error = ""
            self.runtime.mailbox_count = mailbox_count
            self.runtime.archived_count += archived
            if archived:
                self.runtime.last_archive_at = self.runtime.last_scan_at
            return archived
        except (imaplib.IMAP4.error, OSError, NaverMailError, UnicodeError, ValueError) as exc:
            self.runtime.last_scan_at = _utc_timestamp()
            self.runtime.last_error = type(exc).__name__
            return 0

    def list_messages(self, *, limit: int = 50) -> dict[str, object]:
        if not self.config.configured:
            raise NaverMailError("naver_not_configured")
        client = self.imap_factory(self.config.host, self.config.port, timeout=self.config.timeout_seconds)
        messages: list[MailMessage] = []
        mailbox_count = 0
        try:
            status, _data = client.login(self.config.username, self.config.password)
            if status != "OK":
                raise NaverMailError("imap_login_failed")
            mailboxes = discover_mailboxes(client, self.config.folder_roots)
            mailbox_count = len(mailboxes)
            for mailbox in mailboxes:
                status, _data = client.select(quoted_mailbox(mailbox.raw_name), readonly=True)
                if status != "OK":
                    raise NaverMailError("imap_select_failed")
                for uid in reversed(self._search_uids(client)):
                    messages.append(self._fetch_message(client, mailbox, uid))
                    if len(messages) >= limit:
                        break
                client.close()
            messages.sort(key=lambda item: item.received_at, reverse=True)
            return {
                "mailboxCount": mailbox_count,
                "folders": list(self.config.folder_roots),
                "messages": [
                    {
                        "kind": "mail",
                        "direction": "incoming",
                        "mailbox": message.mailbox,
                        "uid": message.uid,
                        "sender": message.sender,
                        "subject": message.subject,
                        "preview": message.preview,
                        "receivedAt": message.received_at,
                        "attachmentCount": len(message.attachments),
                    }
                    for message in messages[:limit]
                ],
            }
        finally:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def _poll(
        self,
        state: dict[str, object],
        *,
        summary_sender: Callable[[MailMessage], object],
        attachment_sender: Callable[[Attachment], object],
        persist: Callable[[], None],
    ) -> tuple[int, int]:
        if not self.config.configured:
            raise NaverMailError("naver_not_configured")
        client = self.imap_factory(self.config.host, self.config.port, timeout=self.config.timeout_seconds)
        archived = 0
        try:
            status, _data = client.login(self.config.username, self.config.password)
            if status != "OK":
                raise NaverMailError("imap_login_failed")
            mailboxes = discover_mailboxes(client, self.config.folder_roots)
            states = state.setdefault("mailboxes", {})
            if not isinstance(states, dict):
                raise NaverMailError("invalid_state")
            for mailbox in mailboxes:
                status, _data = client.select(quoted_mailbox(mailbox.raw_name), readonly=True)
                if status != "OK":
                    raise NaverMailError("imap_select_failed")
                uidvalidity = self._selected_uidvalidity(client)
                uids = self._search_uids(client)
                current = states.get(mailbox.raw_name)
                if not isinstance(current, dict) or current.get("uidValidity") != uidvalidity:
                    states[mailbox.raw_name] = {
                        "displayName": mailbox.display_name,
                        "uidValidity": uidvalidity,
                        "lastUid": max(uids, default=0) if self.config.mark_existing_on_first_run else 0,
                        "pending": {},
                    }
                    persist()
                    client.close()
                    continue
                pending = current.setdefault("pending", {})
                if not isinstance(pending, dict):
                    raise NaverMailError("invalid_pending_state")
                last_uid = int(current.get("lastUid") or 0)
                for uid in (value for value in uids if value > last_uid):
                    mail = self._fetch_message(client, mailbox, uid)
                    progress = pending.setdefault(str(uid), {})
                    if not isinstance(progress, dict):
                        raise NaverMailError("invalid_progress_state")
                    self._deliver(mail, progress, summary_sender, attachment_sender, persist)
                    current["lastUid"] = uid
                    pending.pop(str(uid), None)
                    archived += 1
                    persist()
                current["displayName"] = mailbox.display_name
                current["uidValidity"] = uidvalidity
                client.close()
            return archived, len(mailboxes)
        finally:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def _fetch_message(self, client, mailbox: Mailbox, uid: int) -> MailMessage:
        status, rows = client.uid("fetch", str(uid), "(BODY.PEEK[])")
        if status != "OK":
            raise NaverMailError("imap_fetch_message_failed")
        raw = b"".join(
            row[1]
            for row in rows or []
            if isinstance(row, tuple) and len(row) > 1 and isinstance(row[1], bytes)
        )
        if not raw:
            raise NaverMailError("imap_message_empty")
        return parse_message(raw, mailbox.display_name, uid, self.config.preview_characters)

    def _deliver(
        self,
        mail: MailMessage,
        progress: dict[str, object],
        summary_sender: Callable[[MailMessage], object],
        attachment_sender: Callable[[Attachment], object],
        persist: Callable[[], None],
    ) -> None:
        uploaded = set(progress.get("uploadedAttachments") or [])
        if not progress.get("summaryMessageId"):
            result = summary_sender(mail)
            progress["summaryMessageId"] = _message_id(result)
            persist()
        for index, attachment in enumerate(mail.attachments):
            key = f"{index}:{attachment.filename}:{len(attachment.content)}"
            if key in uploaded or not attachment.content or len(attachment.content) > self.config.max_attachment_bytes:
                continue
            attachment_sender(attachment)
            uploaded.add(key)
            progress["uploadedAttachments"] = sorted(uploaded)
            persist()

    @staticmethod
    def _selected_uidvalidity(client) -> str:
        _code, values = client.response("UIDVALIDITY")
        if not values:
            return ""
        value = values[-1]
        return value.decode("ascii", errors="replace").strip() if isinstance(value, bytes) else str(value).strip()

    @staticmethod
    def _search_uids(client) -> list[int]:
        status, rows = client.uid("search", None, "ALL")
        if status != "OK":
            raise NaverMailError("imap_search_failed")
        raw = b" ".join(row for row in rows or [] if isinstance(row, bytes))
        return sorted(int(value) for value in raw.split() if value.isdigit())


def _message_id(result: object) -> object:
    if isinstance(result, dict):
        return result.get("messageId") or result.get("message_id") or True
    value = getattr(result, "id", None)
    return value or True


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
