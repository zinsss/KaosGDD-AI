from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import imaplib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

from .naver import (
    KST,
    MailMessage,
    Mailbox,
    NaverMailConfig,
    NaverMailError,
    format_sender,
    parse_list_line,
    parse_message,
    quoted_mailbox,
)


class MailOrganizerError(RuntimeError):
    """Raised with a stable, non-secret organizer failure code."""


@dataclass(frozen=True)
class MailOrganizerConfig:
    enabled: bool
    state_path: Path
    max_items: int
    scheduler_poll_seconds: int
    trash_folder: str
    runs_per_day: int
    first_time: str
    second_time: str
    digest_ttl_days: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "MailOrganizerConfig":
        source = os.environ if env is None else env
        runs = int(source.get("MAIL_ORGANIZER_RUNS_PER_DAY", "1"))
        first = validate_time(source.get("MAIL_ORGANIZER_FIRST_TIME", "09:00"), "first_time")
        second = validate_time(source.get("MAIL_ORGANIZER_SECOND_TIME", "17:00"), "second_time")
        if runs not in {1, 2}:
            raise ValueError("invalid_runs_per_day")
        if runs == 2 and first >= second:
            raise ValueError("mail_organizer_times_out_of_order")
        return cls(
            enabled=_env_bool(source.get("MAIL_ORGANIZER_ENABLED", "false")),
            state_path=Path(source.get("MAIL_ORGANIZER_STATE_PATH", "/data/mail/discord-organizer.json")),
            max_items=max(5, min(50, int(source.get("MAIL_ORGANIZER_MAX_ITEMS", "30")))),
            scheduler_poll_seconds=max(30, int(source.get("MAIL_ORGANIZER_SCHEDULER_POLL_SECONDS", "60"))),
            trash_folder=source.get("MAIL_ORGANIZER_TRASH_FOLDER", "Deleted Messages").strip() or "Deleted Messages",
            runs_per_day=runs,
            first_time=first,
            second_time=second,
            digest_ttl_days=max(1, min(30, int(source.get("MAIL_ORGANIZER_DIGEST_TTL_DAYS", "14")))),
        )


@dataclass(frozen=True)
class UnreadMail:
    uid: int
    sender: str
    subject: str
    mailbox_raw: str
    mailbox_name: str
    uidvalidity: str
    received_epoch: float


@dataclass
class OrganizerRuntimeStatus:
    started: bool = False
    last_check_at: str = ""
    last_digest_at: str = ""
    last_error: str = ""
    digest_count: int = 0


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def validate_time(value: object, field: str) -> str:
    try:
        parsed = datetime.strptime(str(value or ""), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"invalid_{field}") from exc
    if parsed.minute % 5:
        raise ValueError(f"invalid_{field}_step")
    return parsed.strftime("%H:%M")


class NaverMailOrganizer:
    def __init__(
        self,
        config: MailOrganizerConfig,
        naver_config: NaverMailConfig,
        imap_factory=None,
    ) -> None:
        self.config = config
        self.naver_config = naver_config
        self.imap_factory = imap_factory or imaplib.IMAP4_SSL
        self.runtime = OrganizerRuntimeStatus()
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        return bool(
            self.naver_config.host
            and self.naver_config.username
            and self.naver_config.password
        )

    def status(self) -> dict[str, object]:
        runtime = self.runtime
        schedule = self.schedule()
        return {
            "ok": (not self.config.enabled) or (self.configured and not runtime.last_error),
            "enabled": self.config.enabled,
            "configured": self.configured,
            "started": runtime.started,
            "statePath": str(self.config.state_path),
            "maxItems": self.config.max_items,
            "schedule": schedule,
            "lastCheckAt": runtime.last_check_at,
            "lastDigestAt": runtime.last_digest_at,
            "lastError": runtime.last_error,
            "digestCount": runtime.digest_count,
        }

    def _default_state(self) -> dict[str, object]:
        return {
            "version": 1,
            "schedule": {
                "runsPerDay": self.config.runs_per_day,
                "firstTime": self.config.first_time,
                "secondTime": self.config.second_time,
                "updatedAt": "",
            },
            "lastSentSlots": {},
            "digests": {},
        }

    def load_state(self) -> dict[str, object]:
        try:
            payload = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_state()
        if not isinstance(payload, dict):
            return self._default_state()
        default = self._default_state()
        return {
            "version": 1,
            "schedule": payload.get("schedule") if isinstance(payload.get("schedule"), dict) else default["schedule"],
            "lastSentSlots": payload.get("lastSentSlots") if isinstance(payload.get("lastSentSlots"), dict) else {},
            "digests": payload.get("digests") if isinstance(payload.get("digests"), dict) else {},
        }

    def save_state(self, state: dict[str, object]) -> None:
        path = self.config.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

    def schedule(self) -> dict[str, object]:
        with self._lock:
            schedule = self.load_state()["schedule"]
            return {
                "runsPerDay": int(schedule.get("runsPerDay", 1)),
                "firstTime": str(schedule.get("firstTime", "09:00")),
                "secondTime": str(schedule.get("secondTime", "17:00")),
                "updatedAt": str(schedule.get("updatedAt", "")),
            }

    def update_schedule(self, runs_per_day: int, first_time: str, second_time: str = "17:00") -> dict[str, object]:
        if runs_per_day not in {1, 2}:
            raise ValueError("invalid_runs_per_day")
        first = validate_time(first_time, "first_time")
        second = validate_time(second_time, "second_time")
        if runs_per_day == 2 and first >= second:
            raise ValueError("mail_organizer_times_out_of_order")
        with self._lock:
            state = self.load_state()
            state["schedule"] = {
                "runsPerDay": runs_per_day,
                "firstTime": first,
                "secondTime": second,
                "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
            }
            self.save_state(state)
            return dict(state["schedule"])

    @contextmanager
    def _client(self):
        if not self.configured:
            raise MailOrganizerError("naver_not_configured")
        client = self.imap_factory(
            self.naver_config.host,
            self.naver_config.port,
            timeout=self.naver_config.timeout_seconds,
        )
        try:
            status, _data = client.login(self.naver_config.username, self.naver_config.password)
            if status != "OK":
                raise MailOrganizerError("imap_login_failed")
            yield client
        finally:
            try:
                if hasattr(client, "unselect"):
                    client.unselect()
            except (imaplib.IMAP4.error, OSError):
                pass
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def _mailboxes(self, client) -> list[Mailbox]:
        status, rows = client.list()
        if status != "OK":
            raise MailOrganizerError("imap_list_failed")
        excluded_flags = {rb"\bsent\b", rb"\bdrafts\b", rb"\btrash\b", rb"\bjunk\b"}
        excluded_names = {self.config.trash_folder.casefold()}
        mailboxes: list[Mailbox] = []
        for row in rows or []:
            parsed = parse_list_line(row)
            if not parsed:
                continue
            _delimiter, mailbox = parsed
            raw = row if isinstance(row, bytes) else str(row).encode()
            flags = raw.split(b")", 1)[0].lower()
            if b"\\noselect" in flags or any(re.search(pattern, flags) for pattern in excluded_flags):
                continue
            if mailbox.display_name.casefold() in excluded_names:
                continue
            mailboxes.append(mailbox)
        if not any(mailbox.raw_name.upper() == "INBOX" for mailbox in mailboxes):
            mailboxes.insert(0, Mailbox("INBOX", "INBOX"))
        return mailboxes

    @staticmethod
    def _uidvalidity(client) -> str:
        _code, values = client.response("UIDVALIDITY")
        if not values:
            return ""
        value = values[-1]
        return value.decode("ascii", errors="replace").strip() if isinstance(value, bytes) else str(value).strip()

    @staticmethod
    def _unread_uids(client) -> list[int]:
        status, rows = client.uid("search", None, "UNSEEN")
        if status != "OK":
            raise MailOrganizerError("imap_search_unread_failed")
        raw = b" ".join(row for row in rows or [] if isinstance(row, bytes))
        return sorted((int(value) for value in raw.split() if value.isdigit()), reverse=True)

    def _select(self, client, mailbox: Mailbox, *, readonly: bool) -> str:
        status, _data = client.select(quoted_mailbox(mailbox.raw_name), readonly=readonly)
        if status != "OK":
            raise MailOrganizerError("imap_select_failed")
        return self._uidvalidity(client)

    def _fetch_header(self, client, mailbox: Mailbox, uid: int, uidvalidity: str) -> UnreadMail:
        status, rows = client.uid(
            "fetch",
            str(uid),
            "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])",
        )
        if status != "OK":
            raise MailOrganizerError("imap_fetch_header_failed")
        raw = b"".join(
            row[1]
            for row in rows or []
            if isinstance(row, tuple) and len(row) > 1 and isinstance(row[1], bytes)
        )
        if not raw:
            raise MailOrganizerError("imap_message_missing")
        message = BytesParser(policy=policy.default).parsebytes(raw)
        try:
            received = parsedate_to_datetime(str(message.get("date", "")))
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            received_epoch = received.timestamp()
        except (AttributeError, TypeError, ValueError, OverflowError):
            received_epoch = 0.0
        return UnreadMail(
            uid=uid,
            sender=format_sender(message.get("from", "")),
            subject=" ".join(str(message.get("subject", "")).split()) or "(No subject)",
            mailbox_raw=mailbox.raw_name,
            mailbox_name=mailbox.display_name,
            uidvalidity=uidvalidity,
            received_epoch=received_epoch,
        )

    def list_unread(self) -> tuple[list[UnreadMail], int]:
        entries: list[UnreadMail] = []
        total = 0
        with self._client() as client:
            for mailbox in self._mailboxes(client):
                uidvalidity = self._select(client, mailbox, readonly=True)
                uids = self._unread_uids(client)
                total += len(uids)
                entries.extend(
                    self._fetch_header(client, mailbox, uid, uidvalidity)
                    for uid in uids[: self.config.max_items]
                )
        entries.sort(key=lambda entry: (entry.received_epoch, entry.uid), reverse=True)
        return entries[: self.config.max_items], total

    def create_digest(self, now: datetime | None = None) -> dict[str, object] | None:
        if not self.config.enabled:
            raise MailOrganizerError("mail_organizer_disabled")
        entries, total = self.list_unread()
        if not entries:
            return None
        now = (now or datetime.now(KST)).astimezone(KST)
        digest_id = secrets.token_hex(4)
        items: dict[str, object] = {}
        order: list[str] = []
        for entry in entries:
            item_id = secrets.token_hex(4)
            order.append(item_id)
            items[item_id] = {
                "uid": entry.uid,
                "subject": entry.subject,
                "sender": entry.sender,
                "mailboxRaw": entry.mailbox_raw,
                "mailboxName": entry.mailbox_name,
                "uidValidity": entry.uidvalidity,
                "archiveProgress": {},
            }
        digest = {
            "id": digest_id,
            "createdAt": now.isoformat(timespec="seconds"),
            "createdEpoch": now.timestamp(),
            "totalUnread": total,
            "channelId": 0,
            "messageId": 0,
            "items": items,
            "order": order,
        }
        with self._lock:
            state = self.load_state()
            self._prune_state(state, now.timestamp())
            state["digests"][digest_id] = digest
            self.save_state(state)
        return digest

    def attach_message(self, digest_id: str, channel_id: int, message_id: int) -> None:
        with self._lock:
            state = self.load_state()
            digest = self._digest(state, digest_id)
            digest["channelId"] = int(channel_id)
            digest["messageId"] = int(message_id)
            self.save_state(state)

    def active_digests(self) -> list[dict[str, object]]:
        with self._lock:
            state = self.load_state()
            return [dict(digest) for digest in state["digests"].values() if int(digest.get("messageId") or 0) > 0]

    def prune_digests(self, now_epoch: float | None = None) -> list[dict[str, object]]:
        with self._lock:
            state = self.load_state()
            expired = self._prune_state(state, now_epoch or time.time())
            self.save_state(state)
            return expired

    def digest(self, digest_id: str) -> dict[str, object]:
        with self._lock:
            return json.loads(json.dumps(self._digest(self.load_state(), digest_id)))

    def fetch_item(self, digest_id: str, item_id: str) -> MailMessage:
        with self._lock:
            digest, item = self._digest_item(self.load_state(), digest_id, item_id)
        mailbox = Mailbox(str(item["mailboxRaw"]), str(item["mailboxName"]))
        with self._client() as client:
            uidvalidity = self._select(client, mailbox, readonly=True)
            if uidvalidity != str(item["uidValidity"]):
                raise MailOrganizerError("mailbox_generation_changed")
            status, rows = client.uid("fetch", str(item["uid"]), "(BODY.PEEK[])")
            if status != "OK":
                raise MailOrganizerError("imap_fetch_message_failed")
            raw = b"".join(
                row[1]
                for row in rows or []
                if isinstance(row, tuple) and len(row) > 1 and isinstance(row[1], bytes)
            )
            if not raw:
                raise MailOrganizerError("imap_message_missing")
            return parse_message(raw, mailbox.display_name, int(item["uid"]), self.naver_config.preview_characters)

    def mark_read(self, digest_id: str, item_id: str) -> dict[str, object]:
        return self._mutate_and_remove(digest_id, [item_id], "read")

    def delete(self, digest_id: str, item_id: str) -> dict[str, object]:
        return self._mutate_and_remove(digest_id, [item_id], "delete")

    def mark_read_all(self, digest_id: str) -> dict[str, object]:
        with self._lock:
            digest = self._digest(self.load_state(), digest_id)
            item_ids = list(digest.get("items", {}))
        return self._mutate_and_remove(digest_id, item_ids, "read")

    def delete_all(self, digest_id: str) -> dict[str, object]:
        with self._lock:
            digest = self._digest(self.load_state(), digest_id)
            item_ids = list(digest.get("items", {}))
        return self._mutate_and_remove(digest_id, item_ids, "delete")

    def remove_imported(self, digest_id: str, item_id: str) -> dict[str, object]:
        with self._lock:
            state = self.load_state()
            digest, _item = self._digest_item(state, digest_id, item_id)
            self._remove_items(digest, [item_id])
            self.save_state(state)
            return json.loads(json.dumps(digest))

    def import_progress(self, digest_id: str, item_id: str) -> dict[str, object]:
        with self._lock:
            _digest, item = self._digest_item(self.load_state(), digest_id, item_id)
            progress = item.get("archiveProgress")
            return json.loads(json.dumps(progress if isinstance(progress, dict) else {}))

    def mark_import_summary(self, digest_id: str, item_id: str, message_id: int) -> None:
        with self._lock:
            state = self.load_state()
            _digest, item = self._digest_item(state, digest_id, item_id)
            progress = item.setdefault("archiveProgress", {})
            progress["summaryMessageId"] = int(message_id)
            self.save_state(state)

    def mark_import_attachment(self, digest_id: str, item_id: str, attachment_key: str) -> None:
        with self._lock:
            state = self.load_state()
            _digest, item = self._digest_item(state, digest_id, item_id)
            progress = item.setdefault("archiveProgress", {})
            uploaded = set(progress.get("uploadedAttachments") or [])
            uploaded.add(attachment_key)
            progress["uploadedAttachments"] = sorted(uploaded)
            self.save_state(state)

    def close_digest(self, digest_id: str) -> dict[str, object]:
        with self._lock:
            state = self.load_state()
            digest = self._digest(state, digest_id)
            result = dict(digest)
            state["digests"].pop(digest_id, None)
            self.save_state(state)
            return result

    def due_digest(self, now: datetime | None = None) -> dict[str, object] | None:
        if not self.config.enabled or not self.configured:
            return None
        now = (now or datetime.now(KST)).astimezone(KST)
        schedule = self.schedule()
        slots = [str(schedule["firstTime"])]
        if int(schedule["runsPerDay"]) == 2:
            slots.append(str(schedule["secondTime"]))
        current = now.strftime("%H:%M")
        due = [slot for slot in slots if slot <= current]
        if not due:
            return None
        with self._lock:
            state = self.load_state()
            if state["lastSentSlots"].get(due[-1]) == now.date().isoformat():
                return None
        return self.create_digest(now)

    def mark_due_sent(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(KST)).astimezone(KST)
        schedule = self.schedule()
        slots = [str(schedule["firstTime"])]
        if int(schedule["runsPerDay"]) == 2:
            slots.append(str(schedule["secondTime"]))
        due = [slot for slot in slots if slot <= now.strftime("%H:%M")]
        with self._lock:
            state = self.load_state()
            for slot in due:
                state["lastSentSlots"][slot] = now.date().isoformat()
            self.save_state(state)

    def record_schedule_result(self, *, sent: bool, error: Exception | None = None) -> None:
        self.runtime.started = True
        self.runtime.last_check_at = datetime.now(KST).isoformat(timespec="seconds")
        self.runtime.last_error = type(error).__name__ if error else ""
        if sent:
            self.runtime.last_digest_at = self.runtime.last_check_at
            self.runtime.digest_count += 1

    def record_manual_digest(self) -> None:
        self.runtime.last_digest_at = datetime.now(KST).isoformat(timespec="seconds")
        self.runtime.digest_count += 1

    def _mutate_and_remove(self, digest_id: str, item_ids: list[str], operation: str) -> dict[str, object]:
        with self._lock:
            state = self.load_state()
            digest = self._digest(state, digest_id)
            items = [digest["items"][item_id] for item_id in item_ids if item_id in digest.get("items", {})]
            if not items:
                return json.loads(json.dumps(digest))
            grouped: dict[tuple[str, str, str], list[int]] = {}
            for item in items:
                key = (str(item["mailboxRaw"]), str(item["mailboxName"]), str(item["uidValidity"]))
                grouped.setdefault(key, []).append(int(item["uid"]))
            with self._client() as client:
                for (raw_name, display_name, expected_uidvalidity), uids in grouped.items():
                    mailbox = Mailbox(raw_name, display_name)
                    uidvalidity = self._select(client, mailbox, readonly=False)
                    if uidvalidity != expected_uidvalidity:
                        raise MailOrganizerError("mailbox_generation_changed")
                    sequence = ",".join(str(uid) for uid in uids)
                    if operation == "read":
                        status, _data = client.uid("store", sequence, "+FLAGS.SILENT", "(\\Seen)")
                    elif operation == "delete":
                        status, _data = client.uid("MOVE", sequence, quoted_mailbox(self.config.trash_folder))
                    else:
                        raise MailOrganizerError("mail_action_invalid")
                    if status != "OK":
                        raise MailOrganizerError(f"imap_{operation}_failed")
            self._remove_items(digest, item_ids)
            self.save_state(state)
            return json.loads(json.dumps(digest))

    @staticmethod
    def _remove_items(digest: dict[str, object], item_ids: list[str]) -> None:
        items = digest.get("items", {})
        for item_id in item_ids:
            items.pop(item_id, None)
        digest["order"] = [item_id for item_id in digest.get("order", []) if item_id in items]

    @staticmethod
    def _digest(state: dict[str, object], digest_id: str) -> dict[str, object]:
        digest = state.get("digests", {}).get(digest_id)
        if not isinstance(digest, dict):
            raise MailOrganizerError("mail_digest_expired")
        return digest

    @classmethod
    def _digest_item(cls, state: dict[str, object], digest_id: str, item_id: str):
        digest = cls._digest(state, digest_id)
        item = digest.get("items", {}).get(item_id)
        if not isinstance(item, dict):
            raise MailOrganizerError("mail_item_unavailable")
        return digest, item

    def _prune_state(self, state: dict[str, object], now_epoch: float) -> list[dict[str, object]]:
        cutoff = now_epoch - self.config.digest_ttl_days * 86400
        expired = []
        for digest_id, digest in list(state.get("digests", {}).items()):
            if not isinstance(digest, dict) or float(digest.get("createdEpoch") or 0) < cutoff:
                if isinstance(digest, dict):
                    expired.append(dict(digest))
                state["digests"].pop(digest_id, None)
        return expired
