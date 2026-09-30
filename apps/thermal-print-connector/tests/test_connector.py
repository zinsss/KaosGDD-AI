from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from pypdf import PdfWriter

from kaos_thermal_print_connector.server import (
    ConnectorConfig,
    ConnectorError,
    _fit_raster_width,
    _threshold_grayscale,
    health_payload,
    job_status,
    submit_job,
)


def receipt_pdf(width: float = 80 / 25.4 * 72, height: float = 400) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    writer.write(output)
    return output.getvalue()


class ThermalPrintConnectorTests(unittest.TestCase):
    def config(self, root: Path, *, mode: str = "cups", output_format: str = "pdf") -> ConnectorConfig:
        return ConnectorConfig(
            token="connector-secret",
            mode=mode,
            printer="receipt-home" if mode == "cups" else "",
            state_path=root / "jobs.json",
            output_format=output_format,
        )

    def payload(self, pdf: bytes | None = None, job_id: str = "a" * 32) -> dict[str, object]:
        document = pdf or receipt_pdf()
        return {
            "version": 1,
            "jobId": job_id,
            "title": "오늘 할 일",
            "kind": "tasks",
            "pdfSha256": hashlib.sha256(document).hexdigest(),
            "pdfBase64": base64.b64encode(document).decode("ascii"),
        }

    def test_dry_run_health_never_claims_printer_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = health_payload(self.config(Path(temporary), mode="dry-run"))

        self.assertEqual(payload["status"], "awaiting_printer")
        self.assertFalse(payload["ready"])

    def test_submits_to_named_cups_queue_and_keeps_only_idempotency_metadata(self) -> None:
        commands = []

        def runner(command, **_kwargs):
            commands.append(command)
            if command[0] == "lpstat":
                return SimpleNamespace(returncode=0, stdout="printer receipt-home is idle", stderr="")
            return SimpleNamespace(returncode=0, stdout="request id is receipt-home-42", stderr="")

        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "kaos_thermal_print_connector.server._run", side_effect=runner
        ):
            config = self.config(Path(temporary))
            first = submit_job(config, self.payload())
            second = submit_job(config, self.payload())

            self.assertEqual(first, second)
            self.assertEqual(first["status"], "submitted")
            self.assertEqual(first["printerJobId"], "receipt-home-42")
            self.assertEqual([command[0] for command in commands], ["lpstat", "lp"])
            self.assertNotIn("pdfBase64", config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(job_status(config, "a" * 32)["status"], "submitted")

    def test_escpos_mode_renders_pdf_and_submits_raw_raster_data(self) -> None:
        commands = []
        submitted = b""

        def runner(command, **_kwargs):
            nonlocal submitted
            commands.append(command)
            if command[0] == "lpstat":
                return SimpleNamespace(returncode=0, stdout="printer receipt-home is idle", stderr="")
            if command[0] == "pdftoppm":
                prefix = Path(command[-1])
                pixels = b"\xff" * 4 + b"\x00" + b"\xff" * (520 * 2 - 5)
                prefix.with_name(f"{prefix.name}-1.pgm").write_bytes(b"P5\n520 2\n255\n" + pixels)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            submitted = Path(command[-1]).read_bytes()
            return SimpleNamespace(returncode=0, stdout="request id is receipt-home-43", stderr="")

        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "kaos_thermal_print_connector.server._run", side_effect=runner
        ):
            result = submit_job(self.config(Path(temporary), output_format="escpos"), self.payload())

        self.assertEqual(result["printerJobId"], "receipt-home-43")
        self.assertEqual([command[0] for command in commands], ["lpstat", "pdftoppm", "lp"])
        self.assertIn("-gray", commands[1])
        self.assertNotIn("-mono", commands[1])
        self.assertEqual(commands[1][commands[1].index("-aa") + 1], "yes")
        self.assertNotIn("-scale-to-x", commands[1])
        self.assertEqual(commands[-1][-3:-1], ["-o", "raw"])
        self.assertTrue(submitted.startswith(b"\x1b@\x1dv0\x00\x40\x00\x02\x00\x80"))
        self.assertTrue(submitted.endswith(b"\n\n\n\x1dV\x01"))

    def test_native_raster_width_is_center_cropped_without_resampling(self) -> None:
        self.assertEqual(_fit_raster_width(16, 1, b"\x0f\xf0", 8), b"\xff")

    def test_narrow_native_raster_is_center_padded(self) -> None:
        self.assertEqual(_fit_raster_width(4, 1, b"\xf0", 8), b"\x3c")

    def test_antialiased_grayscale_uses_controlled_dark_threshold(self) -> None:
        grayscale = bytes((0, 255, 167, 168, 32, 240, 100, 200))

        self.assertEqual(_threshold_grayscale(8, 1, grayscale, 168), b"\xaa")

    def test_rejects_pdf_wider_than_receipt_roll(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ConnectorError) as raised:
            submit_job(self.config(Path(temporary)), self.payload(receipt_pdf(width=400)))

        self.assertEqual(raised.exception.code, "receipt_width_required")

    def test_rejects_unbounded_receipt_height(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ConnectorError) as raised:
            submit_job(self.config(Path(temporary)), self.payload(receipt_pdf(height=6_000)))

        self.assertEqual(raised.exception.code, "invalid_receipt_height")

    def test_rejects_hash_mismatch_before_calling_cups(self) -> None:
        payload = self.payload()
        payload["pdfSha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "kaos_thermal_print_connector.server._run"
        ) as runner, self.assertRaises(ConnectorError) as raised:
            submit_job(self.config(Path(temporary)), payload)

        self.assertEqual(raised.exception.code, "pdf_hash_mismatch")
        runner.assert_not_called()

    def test_corrupt_idempotency_state_fails_closed_before_printing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary))
            config.state_path.write_text("not-json", encoding="utf-8")
            with mock.patch("kaos_thermal_print_connector.server._run") as runner, self.assertRaises(ConnectorError) as raised:
                submit_job(config, self.payload())

        self.assertEqual(raised.exception.code, "connector_state_invalid")
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
