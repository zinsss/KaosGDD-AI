from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from kaos_fax_bridge import main as bridge


def queued_job(root: Path) -> Path:
    job_id = "b" * 32
    pdf = b"%PDF-1.4\n%%EOF"
    document = root / "jobs" / job_id / "document.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(pdf)
    pending = root / "pending"
    pending.mkdir()
    manifest = pending / f"{job_id}.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "jobId": job_id,
                "destination": "022848302",
                "pdfPath": f"jobs/{job_id}/document.pdf",
                "pdfSha256": hashlib.sha256(pdf).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return manifest


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: object) -> SimpleNamespace:
        self.commands.append(command)
        if command[0] == "gs":
            output = next(value.split("=", 1)[1] for value in command if value.startswith("-sOutputFile="))
            Path(output).write_bytes(b"II*\x00fax0")
        if command[0] == "sendfax":
            return SimpleNamespace(stdout="request id is 419", stderr="")
        return SimpleNamespace(stdout="", stderr="")


class OutboundFaxBridgeTests(unittest.TestCase):
    def test_dry_run_converts_but_never_submits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"FAX_BRIDGE_MODE": "dry-run"}, clear=False
        ):
            root = Path(tmp)
            manifest = queued_job(root)
            runner = FakeRunner()
            result = bridge.process_manifest(manifest, root=root, runner=runner, now=1)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual([command[0] for command in runner.commands], ["gs", "tiffinfo"])

    def test_live_mode_submits_only_after_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"FAX_BRIDGE_MODE": "live", "FAXSERVER": "127.0.0.1:4559"}, clear=False
        ):
            root = Path(tmp)
            manifest = queued_job(root)
            runner = FakeRunner()
            result = bridge.process_manifest(manifest, root=root, runner=runner, now=1)

        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["hylafaxJobId"], "419")
        self.assertEqual([command[0] for command in runner.commands], ["gs", "tiffinfo", "sendfax"])

    def test_hash_mismatch_is_rejected_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = queued_job(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["pdfSha256"] = "0" * 64
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            runner = FakeRunner()
            result = bridge.process_manifest(manifest, root=root, runner=runner, now=1)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "pdf_hash_mismatch")
        self.assertEqual(runner.commands, [])

    def test_submission_error_preserves_useful_stderr(self) -> None:
        error = bridge.command_error(
            subprocess.CalledProcessError(1, ["sendfax"], stderr="Login failed: password required"),
            "submission",
        )
        self.assertEqual(error, "submission_failed: Login failed: password required")

    def test_manifest_cannot_escape_queue_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = queued_job(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["pdfPath"] = "../document.pdf"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            result = bridge.process_manifest(manifest, root=root, runner=FakeRunner(), now=1)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "invalid_pdf_path")


if __name__ == "__main__":
    unittest.main()
