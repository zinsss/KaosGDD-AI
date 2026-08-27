from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable


JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
DESTINATION_PATTERN = re.compile(r"^0\d{8,10}$")
REQUEST_ID_PATTERN = re.compile(r"request id is\s+(\d+)", re.IGNORECASE)


class BridgeError(RuntimeError):
    pass


def ensure_shared_directory(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o2770)
    except PermissionError:
        # The bind-mount root can be owned by the host provisioning account.
        pass
    return directory


def queue_root() -> Path:
    return Path(os.environ.get("FAX_BRIDGE_QUEUE_ROOT", "/data/fax-outgoing"))


def mode() -> str:
    value = os.environ.get("FAX_BRIDGE_MODE", "dry-run").strip().lower()
    return value if value in {"dry-run", "live"} else "dry-run"


def poll_seconds() -> int:
    return max(2, int(os.environ.get("FAX_BRIDGE_POLL_SECONDS", "5")))


def fax_server() -> str:
    return os.environ.get("FAXSERVER", "127.0.0.1:4559").strip()


def utc_timestamp(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if now is None else now))


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    ensure_shared_directory(path.parent)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o660)
    os.replace(temporary, path)


def load_manifest(path: Path, root: str | Path | None = None) -> tuple[dict[str, object], Path]:
    resolved_root = Path(root or queue_root()).resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError("invalid_manifest") from exc
    job_id = str(payload.get("jobId") or "")
    destination = str(payload.get("destination") or "")
    relative_pdf = str(payload.get("pdfPath") or "")
    expected_hash = str(payload.get("pdfSha256") or "").lower()
    if payload.get("version") != 1 or not JOB_ID_PATTERN.fullmatch(job_id):
        raise BridgeError("invalid_job_id")
    if path.name != f"{job_id}.json" or not DESTINATION_PATTERN.fullmatch(destination):
        raise BridgeError("invalid_destination")
    if not re.fullmatch(r"jobs/[a-f0-9]{32}/document\.pdf", relative_pdf):
        raise BridgeError("invalid_pdf_path")
    pdf_path = (resolved_root / relative_pdf).resolve()
    if resolved_root not in pdf_path.parents or pdf_path.parent.name != job_id or not pdf_path.is_file():
        raise BridgeError("missing_pdf")
    pdf = pdf_path.read_bytes()
    if not pdf.startswith(b"%PDF-"):
        raise BridgeError("invalid_pdf_signature")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
        raise BridgeError("invalid_pdf_hash")
    if hashlib.sha256(pdf).hexdigest() != expected_hash:
        raise BridgeError("pdf_hash_mismatch")
    return payload, pdf_path


def run_command(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)


def command_error(exc: BaseException, stage: str) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        output = str(exc.stderr or exc.stdout or "").strip()
        detail = output.splitlines()[-1][:400] if output else f"exit_{exc.returncode}"
        return f"{stage}_failed: {detail}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"{stage}_timed_out"
    if isinstance(exc, BridgeError):
        return str(exc)
    return f"{stage}_failed: {type(exc).__name__}"


Runner = Callable[..., subprocess.CompletedProcess[str]]


def convert_pdf(pdf_path: Path, tiff_path: Path, *, runner: Runner = run_command) -> None:
    ensure_shared_directory(tiff_path.parent)
    runner(
        [
            "gs",
            "-q",
            "-sDEVICE=tiffg3",
            "-dNOPAUSE",
            "-dSAFER=true",
            "-sPAPERSIZE=a4",
            "-dFIXEDMEDIA",
            "-dMaxStripSize=0",
            "-dBATCH",
            "-r204x98",
            f"-sOutputFile={tiff_path}",
            str(pdf_path),
        ]
    )
    if not tiff_path.is_file() or tiff_path.stat().st_size < 8:
        raise BridgeError("fax_tiff_not_created")
    if tiff_path.read_bytes()[:4] not in {b"II*\x00", b"MM\x00*"}:
        raise BridgeError("invalid_fax_tiff")
    runner(["tiffinfo", str(tiff_path)])


def submit_fax(destination: str, tiff_path: Path, *, runner: Runner = run_command) -> str:
    result = runner(["sendfax", "-n", "-h", fax_server(), "-d", destination, str(tiff_path)])
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    match = REQUEST_ID_PATTERN.search(output)
    if not match:
        raise BridgeError("hylafax_request_id_missing")
    return match.group(1)


def process_manifest(
    path: Path,
    *,
    root: str | Path | None = None,
    runner: Runner = run_command,
    now: float | None = None,
) -> dict[str, object]:
    selected_root = Path(root or queue_root())
    result_path = selected_root / "results" / path.name
    processed_path = selected_root / "processed" / path.name
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    job_id = path.stem
    stage = "manifest"
    try:
        manifest, pdf_path = load_manifest(path, selected_root)
        job_id = str(manifest["jobId"])
        tiff_path = selected_root / "jobs" / job_id / "document.tif"
        stage = "conversion"
        convert_pdf(pdf_path, tiff_path, runner=runner)
        if mode() == "dry-run":
            result: dict[str, object] = {
                "status": "dry_run",
                "jobId": job_id,
                "destination": manifest["destination"],
                "tiffPath": f"jobs/{job_id}/document.tif",
                "completedAt": utc_timestamp(now),
            }
        else:
            stage = "submission"
            request_id = submit_fax(str(manifest["destination"]), tiff_path, runner=runner)
            result = {
                "status": "submitted",
                "jobId": job_id,
                "destination": manifest["destination"],
                "hylafaxJobId": request_id,
                "submittedAt": utc_timestamp(now),
            }
    except (BridgeError, OSError, subprocess.SubprocessError, ValueError) as exc:
        result = {
            "status": "failed",
            "jobId": job_id,
            "error": command_error(exc, stage),
            "completedAt": utc_timestamp(now),
        }
    atomic_json(result_path, result)
    ensure_shared_directory(processed_path.parent)
    if path.exists():
        shutil.move(str(path), str(processed_path))
    return result


def process_pending(*, root: str | Path | None = None, runner: Runner = run_command) -> list[dict[str, object]]:
    selected_root = Path(root or queue_root())
    pending = ensure_shared_directory(selected_root / "pending")
    return [process_manifest(path, root=selected_root, runner=runner) for path in sorted(pending.glob("*.json"))]


def main() -> None:
    root = queue_root()
    for name in ("pending", "processed", "results", "jobs"):
        ensure_shared_directory(root / name)
    print(f"KaosGDD fax bridge started in {mode()} mode", flush=True)
    while True:
        for result in process_pending(root=root):
            print(f"Fax bridge job {result.get('jobId')}: {result.get('status')}", flush=True)
        time.sleep(poll_seconds())


if __name__ == "__main__":
    main()
