from http import HTTPStatus
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kaos_office_fax_connector.server import (
    ConnectorConfig,
    ConnectorError,
    incoming_events,
    job_status,
    submit_job,
)


class OfficeFaxConnectorTests(unittest.TestCase):
    def config(self, root: Path) -> ConnectorConfig:
        return ConnectorConfig(
            token="not-a-real-token",
            queue_root=root / "queue",
            recvq=root / "hylafax" / "recvq",
            xferfaxlog=root / "hylafax" / "log" / "xferfaxlog",
            doneq=root / "hylafax" / "doneq",
            state_path=root / "state.json",
            minimum_file_age_seconds=0,
        )

    def payload(self, job_id: str = "a" * 32) -> dict[str, object]:
        return {
            "jobId": job_id,
            "destination": "022848302",
            "sender": "discord:1",
            "messageId": "discord:1:2:3:4",
            "filename": "요청서.pdf",
            "pdfSha256": "hash",
            "pdfBase64": base64.b64encode(b"%PDF-test").decode("ascii"),
        }

    def test_submit_job_writes_existing_bridge_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.config(root)

            result = submit_job(config, self.payload())

            manifest = json.loads((root / "queue" / "pending" / f"{'a' * 32}.json").read_text())
            self.assertEqual(result["status"], "queued")
            self.assertEqual(manifest["pdfPath"], f"jobs/{'a' * 32}/document.pdf")
            self.assertEqual((root / "queue" / "jobs" / ("a" * 32) / "document.pdf").read_bytes(), b"%PDF-test")

    def test_job_status_maps_doneq_to_sent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.config(root)
            result = root / "queue" / "results" / f"{'a' * 32}.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"status": "submitted", "hylafaxJobId": "42"}), encoding="utf-8")
            doneq = root / "hylafax" / "doneq" / "q42"
            doneq.parent.mkdir(parents=True)
            doneq.write_text("statuscode:0\nstate:7\nreturned:2\n", encoding="utf-8")

            status = job_status(config, "a" * 32)

        self.assertEqual(status["status"], "sent")
        self.assertEqual(status["hylafaxJobId"], "42")

    def test_incoming_events_convert_tiff_to_pdf_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.config(root)
            fax = root / "hylafax" / "recvq" / "fax000000007.tif"
            fax.parent.mkdir(parents=True)
            fax.write_bytes(b"TIFF")
            config.xferfaxlog.parent.mkdir(parents=True)
            config.xferfaxlog.write_text(
                '08/12/26 13:55\tRECV\t000000007\tttyACM0\trecvq/fax000000007.tif\t""\tfax\t""\t"0547337787"\t9600\t1\n',
                encoding="utf-8",
            )

            with mock.patch(
                "kaos_office_fax_connector.server.tiff_to_pdf",
                return_value=b"%PDF-converted",
            ):
                events = incoming_events(config)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["remote"], "0547337787")
        self.assertEqual(events[0]["filename"], "2026-08-12-13:55_FROM_0547337787.pdf")
        self.assertEqual(base64.b64decode(events[0]["pdfBase64"]), b"%PDF-converted")

    def test_rejects_invalid_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ConnectorError) as raised:
                submit_job(self.config(Path(temporary)), self.payload("bad"))

        self.assertEqual(raised.exception.status, HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    unittest.main()
