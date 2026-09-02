from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import Mock, patch

from kaos_governor import api
from kaos_governor.fax import FaxError


class FakeFax:
    fax_id = "a" * 32

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.rows = [
            {
                "direction": "incoming",
                "faxId": self.fax_id,
                "title": "received.pdf",
                "status": "archived",
                "hasDocument": True,
            },
            {
                "direction": "outgoing",
                "jobId": "sent-1",
                "title": "sent.pdf",
                "status": "sent",
            },
            {
                "direction": "outgoing",
                "jobId": "failed-1",
                "title": "failed.pdf",
                "status": "failed",
            },
            {
                "direction": "outgoing",
                "jobId": "queued-1",
                "title": "queued.pdf",
                "status": "queued",
            },
        ]

    def recent_items(self, *, limit: int | None = 50) -> list[dict[str, object]]:
        self.calls.append(limit)
        return list(self.rows if limit is None else self.rows[:limit])

    def incoming_document_bytes(self, fax_id: str) -> dict[str, object]:
        self.calls.append(("document", fax_id))
        return {
            "faxId": fax_id,
            "filename": "받은 팩스.pdf",
            "contentType": "application/pdf",
            "content": b"%PDF-retained",
        }


class CaptureHandler(api.Handler):
    def __init__(self, path: str, headers: dict[str, str]) -> None:
        self.path = path
        self.headers = headers
        self.wfile = BytesIO()
        self.status = 0
        self.response_headers: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.response_headers[keyword] = value

    def end_headers(self) -> None:
        return None


class FaxApiTests(unittest.TestCase):
    def test_list_returns_archive_counts_and_retained_document_url(self) -> None:
        service = FakeFax()

        payload = api.fax_items_payload("limit=2", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [None])
        self.assertEqual(payload["mode"], "all")
        self.assertEqual(payload["resultCount"], 4)
        self.assertEqual(payload["counts"], {"all": 4, "received": 1, "sent": 1, "failed": 1})
        self.assertEqual(payload["attention"], {"failed": 1})
        self.assertEqual(len(payload["items"]), 2)  # type: ignore[arg-type]
        self.assertEqual(
            payload["items"][0]["documentUrl"],  # type: ignore[index]
            f"/api/fax/items/{service.fax_id}/document",
        )
        self.assertEqual(payload["items"][1]["documentUrl"], "")  # type: ignore[index]

    def test_safe_modes_filter_received_sent_and_failed(self) -> None:
        service = FakeFax()

        received = api.fax_items_payload("mode=received", service)  # type: ignore[arg-type]
        sent = api.fax_items_payload("mode=sent", service)  # type: ignore[arg-type]
        failed = api.fax_items_payload("mode=failed", service)  # type: ignore[arg-type]

        self.assertEqual([item["title"] for item in received["items"]], ["received.pdf"])  # type: ignore[index]
        self.assertEqual([item["title"] for item in sent["items"]], ["sent.pdf"])  # type: ignore[index]
        self.assertEqual([item["title"] for item in failed["items"]], ["failed.pdf"])  # type: ignore[index]

    def test_mode_and_limit_are_strictly_bounded(self) -> None:
        for query in ("mode=pending", "limit=0", "limit=101", "limit=nope"):
            with self.subTest(query=query), self.assertRaises(FaxError):
                api.fax_items_payload(query, FakeFax())  # type: ignore[arg-type]

        self.assertEqual(api.fax_status_for_error(FaxError("fax_mode_invalid")), 400)
        self.assertEqual(api.fax_status_for_error(FaxError("fax_document_not_found")), 404)

    def test_acknowledge_failed_job_payload_uses_safe_job_id(self) -> None:
        service = FakeFax()
        service.acknowledge_failed_job = Mock(
            return_value={"jobId": "failed-1", "status": "failed", "attentionAcknowledged": True}
        )

        payload = api.fax_acknowledge_payload("failed-1", service)  # type: ignore[arg-type]

        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["attentionAcknowledged"], True)
        service.acknowledge_failed_job.assert_called_once_with("failed-1")
        self.assertEqual(api.fax_acknowledge_job_id("/api/fax/items/failed-1/ack"), "failed-1")
        self.assertEqual(api.fax_acknowledge_job_id("/api/fax/items/../ack"), "")
        self.assertEqual(api.fax_acknowledge_job_id("/api/fax/items/bad%2Fid/ack"), "")

    def test_document_route_requires_exact_32_hex_id(self) -> None:
        upper_id = "ABCDEF0123456789ABCDEF0123456789"

        self.assertEqual(
            api.fax_document_id(f"/api/fax/items/{upper_id}/document"),
            upper_id.lower(),
        )
        self.assertEqual(api.fax_document_id("/api/fax/items/not-an-id/document"), "")
        self.assertEqual(api.fax_document_id(f"/api/fax/items/{'a' * 31}/document"), "")

    def test_document_payload_returns_raw_pdf_and_safe_filename(self) -> None:
        service = FakeFax()

        content, filename = api.fax_document_payload(service.fax_id, service)  # type: ignore[arg-type]

        self.assertEqual(content, b"%PDF-retained")
        self.assertEqual(filename, "받은 팩스.pdf")
        self.assertEqual(service.calls, [("document", service.fax_id)])

    def test_list_handler_rejects_non_personal_cloudflare_identity(self) -> None:
        handler = CaptureHandler("/api/fax/items", {"Host": "family.kaosgdd.net"})
        browse = Mock(return_value={"ok": True, "items": []})

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("family", "family@example.com")),
            patch.object(api, "fax_items_payload", browse),
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 404)
        self.assertEqual(json.loads(handler.wfile.getvalue())["error"], "main_profile_required")
        browse.assert_not_called()

    def test_document_handler_returns_inline_pdf_after_personal_access(self) -> None:
        fax_id = "c" * 32
        handler = CaptureHandler(
            f"/api/fax/items/{fax_id}/document",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "fax_document_payload", return_value=(b"%PDF-inline", "받은 팩스.pdf")),
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.response_headers["Content-Type"], "application/pdf")
        self.assertTrue(handler.response_headers["Content-Disposition"].startswith("inline;"))
        self.assertEqual(handler.wfile.getvalue(), b"%PDF-inline")


if __name__ == "__main__":
    unittest.main()
