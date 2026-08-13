from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
from typing import Mapping
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")
FAX_FILENAME = re.compile(r"fax0*([0-9]+)\.tif", re.IGNORECASE)
DOMESTIC_NUMBER = re.compile(r"^0\d{8,10}$")


class FaxError(ValueError):
    pass


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise FaxError(f"{name} must be true or false")


def _int(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise FaxError(f"{name} must be an integer") from exc
    return max(minimum, value)


def _secret(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    path = env.get(f"{name}_FILE", "").strip()
    if value and path:
        raise FaxError(f"{name} ambiguous")
    if not path:
        return value
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FaxError(f"{name}_FILE unreadable") from exc


@dataclass(frozen=True)
class FaxConfig:
    enabled: bool
    message_intake: bool
    state_path: Path
    queue_root: Path
    legacy_state_path: Path
    recvq: Path
    xferfaxlog: Path
    doneq: Path
    poll_seconds: int
    minimum_file_age_seconds: int
    max_pdf_bytes: int
    mark_existing_on_first_run: bool
    delete_source_on_success: bool
    transport: str = "local"
    connector_base_url: str = ""
    connector_token: str = ""
    connector_timeout_seconds: int = 20

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "FaxConfig":
        source = os.environ if env is None else env
        transport = source.get("FAX_TRANSPORT", "local").strip().lower() or "local"
        if transport not in {"local", "connector"}:
            raise FaxError("FAX_TRANSPORT must be local or connector")
        return cls(
            enabled=_bool(source, "FAX_DISCORD_ENABLED"),
            message_intake=_bool(source, "FAX_DISCORD_MESSAGE_INTAKE"),
            state_path=Path(source.get("FAX_DISCORD_STATE_PATH", "/data/fax/state.json")),
            queue_root=Path(source.get("FAX_OUTGOING_QUEUE_ROOT", "/integrations/fax-outgoing")),
            legacy_state_path=Path(
                source.get("FAX_LEGACY_OUTGOING_STATE_PATH", "/integrations/fax-outgoing/state.json")
            ),
            recvq=Path(source.get("FAX_HYLAFAX_RECVQ", "/integrations/hylafax/recvq")),
            xferfaxlog=Path(
                source.get("FAX_HYLAFAX_XFERFAXLOG", "/integrations/hylafax/log/xferfaxlog")
            ),
            doneq=Path(source.get("FAX_HYLAFAX_DONEQ", "/integrations/hylafax/doneq")),
            poll_seconds=_int(source, "FAX_DISCORD_POLL_SECONDS", 20, 5),
            minimum_file_age_seconds=_int(source, "FAX_MIN_FILE_AGE_SECONDS", 60, 0),
            max_pdf_bytes=_int(source, "FAX_MAX_PDF_MB", 20, 1) * 1024 * 1024,
            mark_existing_on_first_run=_bool(source, "FAX_MARK_EXISTING_ON_FIRST_RUN", True),
            delete_source_on_success=_bool(source, "FAX_DELETE_DISCORD_SOURCE_ON_SUCCESS", True),
            transport=transport,
            connector_base_url=source.get("FAX_CONNECTOR_BASE_URL", "").strip().rstrip("/"),
            connector_token=_secret(source, "FAX_CONNECTOR_TOKEN"),
            connector_timeout_seconds=_int(source, "FAX_CONNECTOR_TIMEOUT_SECONDS", 20, 1),
        )


@dataclass(frozen=True)
class FaxRequest:
    destination: str
    sender: str
    source_id: str
    filename: str
    pdf: bytes
    pdf_sha256: str


@dataclass(frozen=True)
class FaxAction:
    key: str
    kind: str
    content: str = ""
    path: Path | None = None
    filename: str = ""
    channel_id: int = 0
    message_ids: tuple[int, ...] = ()
    content_bytes: bytes = b""


class OfficeFaxConnectorClient:
    def __init__(self, config: FaxConfig, *, urlopen=None) -> None:
        self.config = config
        self._urlopen = urlopen or urllib.request.urlopen

    def submit(self, job_id: str, request: FaxRequest, source_metadata: Mapping[str, object]) -> dict[str, object]:
        payload = {
            "version": 1,
            "jobId": job_id,
            "destination": request.destination,
            "sender": request.sender,
            "messageId": request.source_id,
            "filename": request.filename,
            "pdfSha256": request.pdf_sha256,
            "pdfBase64": base64.b64encode(request.pdf).decode("ascii"),
            "source": "kaos-governor",
            "sourceMetadata": dict(source_metadata),
        }
        return self._request("POST", "/v1/fax/jobs", payload)

    def job_status(self, job_id: str) -> dict[str, object]:
        return self._request("GET", f"/v1/fax/jobs/{job_id}", None)

    def incoming_events(self) -> list[Mapping[str, object]]:
        result = self._request("GET", "/v1/fax/incoming", None)
        events = result.get("events")
        if not isinstance(events, list):
            return []
        return [item for item in events if isinstance(item, Mapping)]

    def _request(self, method: str, path: str, payload: dict[str, object] | None) -> dict[str, object]:
        if not self.config.connector_base_url or not self.config.connector_token:
            raise FaxError("fax_connector_not_configured")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.config.connector_base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.connector_token}",
                "Accept": "application/json",
                "User-Agent": "KaosGovernor/fax-connector",
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.connector_timeout_seconds) as response:
                response_body = response.read()
            if response.status < 200 or response.status >= 300:
                raise FaxError(f"fax_connector_http_{response.status}")
        except urllib.error.HTTPError as exc:
            raise FaxError(f"fax_connector_http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FaxError("fax_connector_request_failed") from exc
        try:
            decoded = json.loads(response_body.decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError as exc:
            raise FaxError("fax_connector_invalid_json") from exc
        if not isinstance(decoded, dict):
            raise FaxError("fax_connector_invalid_json")
        return decoded


def normalize_destination(raw: str) -> str:
    compact = re.sub(r"[\s().-]+", "", str(raw or "").strip())
    if compact.startswith("+82"):
        compact = f"0{compact[3:]}"
    if not DOMESTIC_NUMBER.fullmatch(compact):
        raise FaxError("invalid_domestic_fax_number")
    return compact


def request_from_pdf(*, destination: str, sender: str, source_id: str, filename: str, pdf: bytes, max_bytes: int) -> FaxRequest:
    destination = normalize_destination(destination)
    filename = unicodedata.normalize("NFC", Path(filename or "fax.pdf").name)
    if not sender.strip() or not source_id.strip():
        raise FaxError("source_identity_required")
    if not filename.lower().endswith(".pdf"):
        raise FaxError("pdf_attachment_required")
    if not pdf.startswith(b"%PDF-"):
        raise FaxError("invalid_pdf_signature")
    if not pdf or len(pdf) > max_bytes:
        raise FaxError("pdf_size_invalid")
    return FaxRequest(destination, sender, source_id, filename, pdf, hashlib.sha256(pdf).hexdigest())


def request_job_id(request: FaxRequest) -> str:
    value = "\0".join((request.source_id, request.destination, request.pdf_sha256)).encode()
    return hashlib.sha256(value).hexdigest()[:32]


def _timestamp(now: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, UTC).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o2770)
    except PermissionError:
        pass


def _atomic_bytes(path: Path, value: bytes) -> None:
    _ensure_directory(path.parent)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(value)
    os.chmod(temporary, 0o660)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_bytes(path, json.dumps(value, indent=2, sort_keys=True).encode("utf-8"))


def parse_doneq(path: Path) -> dict[str, object]:
    values: dict[str, str] = {}
    current = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if current and raw.endswith("\\"):
            values[current] = f"{values[current]}\n{raw[:-1]}"
            continue
        current = ""
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip().lower()
        values[key] = value[:-1] if value.endswith("\\") else value.strip()
        if value.endswith("\\"):
            current = key
    status = values.get("status", "").strip()
    return {
        **values,
        "sent": values.get("statuscode", "").strip() == "0"
        or (values.get("state", "").strip() == "7" and values.get("returned", "").strip() == "2" and not status),
    }


def _parse_xferfaxlog(path: Path) -> dict[str, dict[str, str]]:
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


def _remote_number(value: str) -> str:
    digits = re.sub(r"\D+", "", value)
    if digits.startswith("82") and len(digits) >= 10:
        digits = f"0{digits[2:]}"
    return digits or "unknown"


def _received_time(value: str, path: Path) -> datetime:
    for pattern in ("%m/%d/%y %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=KST)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, KST)


def _sent_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M")


class FaxService:
    def __init__(self, config: FaxConfig, *, connector: OfficeFaxConnectorClient | None = None) -> None:
        self.config = config
        self.connector = connector or OfficeFaxConnectorClient(config)
        self._lock = threading.RLock()
        self.last_scan_at = ""
        self.last_error = ""

    def _load(self) -> dict:
        value = _read_json(self.config.state_path)
        value["jobs"] = value.get("jobs") if isinstance(value.get("jobs"), dict) else {}
        value["delivered"] = value.get("delivered") if isinstance(value.get("delivered"), dict) else {}
        value["prompts"] = value.get("prompts") if isinstance(value.get("prompts"), dict) else {}
        return value

    def _save(self, state: dict) -> None:
        state["version"] = 1
        _atomic_json(self.config.state_path, state)

    def remember_prompt(self, source_message_id: int, prompt_message_id: int) -> None:
        with self._lock:
            state = self._load()
            state["prompts"][str(source_message_id)] = prompt_message_id
            self._save(state)

    def submit(self, request: FaxRequest, source_metadata: dict[str, object]) -> tuple[dict, bool]:
        with self._lock:
            state = self._load()
            job_id = request_job_id(request)
            if job_id in state["jobs"]:
                return state["jobs"][job_id], False
            if self.config.transport == "connector":
                return self._submit_connector(state, job_id, request, source_metadata)
            job_dir = self.config.queue_root / "jobs" / job_id
            document = job_dir / "document.pdf"
            manifest = {
                "version": 1,
                "jobId": job_id,
                "destination": request.destination,
                "sender": request.sender,
                "messageId": request.source_id,
                "filename": request.filename,
                "pdfPath": f"jobs/{job_id}/document.pdf",
                "pdfSha256": request.pdf_sha256,
                "createdAt": _timestamp(),
            }
            if not document.exists():
                _atomic_bytes(document, request.pdf)
            pending = self.config.queue_root / "pending" / f"{job_id}.json"
            processed = self.config.queue_root / "processed" / f"{job_id}.json"
            if not pending.exists() and not processed.exists():
                _atomic_json(pending, manifest)
            prompt_id = state["prompts"].pop(str(source_metadata.get("messageId") or ""), 0)
            if prompt_id:
                source_metadata["instructionMessageId"] = int(prompt_id)
            job = {
                **manifest,
                "source": "discord",
                "sourceMetadata": source_metadata,
                "status": "queued",
            }
            state["jobs"][job_id] = job
            self._save(state)
            return job, True

    def _submit_connector(
        self,
        state: dict,
        job_id: str,
        request: FaxRequest,
        source_metadata: dict[str, object],
    ) -> tuple[dict, bool]:
        response = self.connector.submit(job_id, request, source_metadata)
        prompt_id = state["prompts"].pop(str(source_metadata.get("messageId") or ""), 0)
        if prompt_id:
            source_metadata["instructionMessageId"] = int(prompt_id)
        status = str(response.get("status") or "queued")
        if status not in {"queued", "submitted", "sent", "failed"}:
            status = "queued"
        job = {
            "version": 1,
            "jobId": job_id,
            "destination": request.destination,
            "sender": request.sender,
            "messageId": request.source_id,
            "filename": request.filename,
            "pdfSha256": request.pdf_sha256,
            "createdAt": _timestamp(),
            "source": "discord",
            "sourceMetadata": source_metadata,
            "status": status,
            "connectorResult": response,
        }
        if response.get("hylafaxJobId"):
            job["hylafaxJobId"] = str(response["hylafaxJobId"])
        if response.get("completedAt"):
            job["completedAt"] = str(response["completedAt"])
        if response.get("error"):
            job["error"] = str(response["error"])
        state["jobs"][job_id] = job
        self._save(state)
        return job, True

    def _reconcile_jobs(self, state: dict) -> None:
        for job_id, job in state["jobs"].items():
            if job.get("status") not in {"queued", "submitted"}:
                continue
            if self.config.transport == "connector":
                self._reconcile_connector_job(job_id, job)
                continue
            result = _read_json(self.config.queue_root / "results" / f"{job_id}.json")
            if job.get("status") == "queued" and result:
                if result.get("status") == "submitted" and str(result.get("hylafaxJobId") or "").isdigit():
                    job["status"] = "submitted"
                    job["hylafaxJobId"] = str(result["hylafaxJobId"])
                    job["bridgeResult"] = result
                elif result.get("status") == "failed":
                    job["status"] = "failed"
                    job["error"] = str(result.get("error") or "submission_failed")
                    job["completedAt"] = str(result.get("completedAt") or "")
            hylafax_id = str(job.get("hylafaxJobId") or "")
            done = self.config.doneq / f"q{hylafax_id}"
            if job.get("status") != "submitted" or not hylafax_id or not done.is_file():
                continue
            result = parse_doneq(done)
            job["status"] = "sent" if result["sent"] else "failed"
            job["error"] = "" if result["sent"] else str(result.get("status") or "transmission_failed")
            job["completedAt"] = _timestamp(done.stat().st_mtime)
            job["doneq"] = result

    def _reconcile_connector_job(self, job_id: str, job: dict) -> None:
        result = self.connector.job_status(job_id)
        status = str(result.get("status") or job.get("status") or "")
        if status not in {"queued", "submitted", "sent", "failed"}:
            return
        job["status"] = status
        job["connectorResult"] = result
        if result.get("hylafaxJobId"):
            job["hylafaxJobId"] = str(result["hylafaxJobId"])
        if result.get("completedAt"):
            job["completedAt"] = str(result["completedAt"])
        if status == "failed":
            job["error"] = str(result.get("error") or "transmission_failed")
        elif status == "sent":
            job["error"] = ""

    def _incoming_actions(self) -> list[FaxAction]:
        if self.config.transport == "connector":
            return self._connector_incoming_actions()
        details = _parse_xferfaxlog(self.config.xferfaxlog)
        now = time.time()
        actions = []
        if not self.config.recvq.is_dir():
            return actions
        for path in sorted(self.config.recvq.glob("fax*.tif")):
            stat = path.stat()
            if now - stat.st_mtime < self.config.minimum_file_age_seconds:
                continue
            match = FAX_FILENAME.fullmatch(path.name)
            if not match:
                continue
            info = details.get(f"recvq/{path.name}") or details.get(str(path)) or {}
            commid = str(info.get("commid") or match.group(1).zfill(9))
            remote = _remote_number(str(info.get("remote") or ""))
            pages = str(info.get("pages") or "")
            received = _received_time(str(info.get("receivedAt") or ""), path)
            key = f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}"
            body = ["Incoming fax", f"Received {path.name}", f"From: {remote}"]
            if pages:
                body.append(f"Pages: {pages}")
            if commid:
                body.append(f"CommID: {commid}")
            actions.extend(
                (
                    FaxAction(f"incoming:notify:{key}", "notification", "\n".join(body)),
                    FaxAction(
                        f"incoming:archive:{key}",
                        "archive",
                        path=path,
                        filename=f"{received:%Y-%m-%d-%H:%M}_FROM_{remote}.pdf",
                    ),
                )
            )
        return actions

    def _connector_incoming_actions(self) -> list[FaxAction]:
        actions = []
        for event in self.connector.incoming_events():
            event_id = str(event.get("eventId") or "")
            filename = unicodedata.normalize("NFC", str(event.get("filename") or "incoming-fax.pdf"))
            remote = str(event.get("remote") or "unknown")
            commid = str(event.get("commid") or "")
            pages = str(event.get("pages") or "")
            try:
                pdf = base64.b64decode(str(event.get("pdfBase64") or ""), validate=True)
            except ValueError:
                continue
            if not event_id or not pdf.startswith(b"%PDF-"):
                continue
            body = ["Incoming fax", f"From: {remote}"]
            if pages:
                body.append(f"Pages: {pages}")
            if commid:
                body.append(f"CommID: {commid}")
            actions.extend(
                (
                    FaxAction(f"incoming:notify:{event_id}", "notification", "\n".join(body)),
                    FaxAction(
                        f"incoming:archive:{event_id}",
                        "archive",
                        filename=filename,
                        content_bytes=pdf,
                    ),
                )
            )
        return actions

    def _job_actions(self, source: str, job_id: str, job: dict) -> list[FaxAction]:
        status = str(job.get("status") or "")
        destination = str(job.get("destination") or "unknown")
        filename = unicodedata.normalize("NFC", str(job.get("filename") or "fax.pdf"))
        prefix = f"outgoing:{source}:{job_id}"
        actions = []
        if status in {"queued", "submitted", "sent", "failed"}:
            actions.append(FaxAction(f"{prefix}:queued", "notification", f"Fax queued to send.\n: to {destination}\n: {filename}"))
        if status in {"submitted", "sent"} or (status == "failed" and job.get("hylafaxJobId")):
            actions.append(FaxAction(f"{prefix}:sending", "notification", f"Sending fax to {destination}.\n: {filename}"))
        if status == "sent":
            actions.append(FaxAction(f"{prefix}:sent", "notification", f"Fax successfully sent.\n: to {destination}\n: {filename}"))
            document = self.config.queue_root / "jobs" / job_id / "document.pdf"
            if self.config.transport == "local" and document.is_file():
                completed = _sent_time(str(job.get("completedAt") or ""))
                content = f"Sent fax.\n: to {destination}" + (f"\n: {completed}" if completed else "")
                actions.append(FaxAction(f"{prefix}:archive", "archive", content, document, filename))
            if source == "discord" and self.config.delete_source_on_success:
                metadata = job.get("sourceMetadata") if isinstance(job.get("sourceMetadata"), dict) else {}
                ids = []
                for name in ("messageId", "commandMessageId", "instructionMessageId"):
                    try:
                        value = int(metadata.get(name) or 0)
                    except (TypeError, ValueError):
                        value = 0
                    if value > 0:
                        ids.append(value)
                actions.append(
                    FaxAction(
                        f"{prefix}:cleanup",
                        "cleanup",
                        channel_id=int(metadata.get("channelId") or 0),
                        message_ids=tuple(sorted(set(ids))),
                    )
                )
        elif status == "failed":
            error = str(job.get("error") or "transmission_failed")
            actions.append(FaxAction(f"{prefix}:failed", "notification", f"Fax failed\n: to {destination}\n: {filename}\n: {error}"))
        return actions

    def scan_actions(self) -> list[FaxAction]:
        if not self.config.enabled:
            return []
        with self._lock:
            state = self._load()
            self._reconcile_jobs(state)
            candidates = self._incoming_actions()
            for job_id, job in state["jobs"].items():
                candidates.extend(self._job_actions("discord", job_id, job))
            legacy = _read_json(self.config.legacy_state_path)
            legacy_jobs = legacy.get("jobs") if isinstance(legacy.get("jobs"), dict) else {}
            for job_id, job in legacy_jobs.items():
                if isinstance(job, dict):
                    candidates.extend(self._job_actions("legacy", str(job_id), job))
            if not state.get("initialized") and self.config.mark_existing_on_first_run:
                for action in candidates:
                    state["delivered"][action.key] = {"at": _timestamp(), "status": "baselined"}
                state["initialized"] = True
                self._save(state)
                self.last_scan_at = _timestamp()
                self.last_error = ""
                return []
            state["initialized"] = True
            self._save(state)
            self.last_scan_at = _timestamp()
            self.last_error = ""
            return [action for action in candidates if action.key not in state["delivered"]]

    def acknowledge(self, action: FaxAction) -> None:
        with self._lock:
            state = self._load()
            state["delivered"][action.key] = {"at": _timestamp(), "status": "delivered"}
            self._save(state)

    def record_error(self, exc: Exception) -> None:
        self.last_error = f"{type(exc).__name__}: {exc}"

    def status(self) -> dict[str, object]:
        state = self._load()
        return {
            "enabled": self.config.enabled,
            "messageIntake": self.config.message_intake,
            "transport": self.config.transport,
            "configured": bool(
                self.config.state_path
                and (
                    self.config.transport == "local"
                    and self.config.queue_root
                    and self.config.recvq
                    or self.config.transport == "connector"
                    and self.config.connector_base_url
                    and self.config.connector_token
                )
            ),
            "statePath": str(self.config.state_path),
            "queueRoot": str(self.config.queue_root),
            "connectorUrlConfigured": bool(self.config.connector_base_url),
            "lastScanAt": self.last_scan_at,
            "lastError": self.last_error,
            "trackedJobs": len(state["jobs"]),
            "deliveredActions": len(state["delivered"]),
        }
