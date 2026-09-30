from __future__ import annotations

import base64
from datetime import datetime
import io
import json
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from kaos_governor import api, thermal_print


SAMPLE_DOCUMENT = {
    "version": 1,
    "kind": "memo",
    "title": "진료 준비 메모",
    "subtitle": "Memo #42",
    "meta": [{"label": "Updated", "value": "2026-09-28 19:10"}],
    "sections": [
        {
            "heading": "확인 목록",
            "items": [
                {"title": "검사지 챙기기", "checked": True},
                {"title": "예약 시간 확인", "checked": False, "meta": "10:30"},
            ],
        }
    ],
    "body": "## 메모\n\n**중요한 내용**을 확인합니다.\n\n- 첫 번째\n- 두 번째",
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class CaptureHandler(api.Handler):
    def __init__(self, path: str, headers: dict[str, str], body: bytes = b"") -> None:
        self.path = path
        self.headers = {**headers, "Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = 0
        self.response_headers: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.response_headers[keyword] = value

    def end_headers(self) -> None:
        return None


class ThermalPrintTests(unittest.TestCase):
    def test_renders_korean_document_at_80mm_width(self) -> None:
        pdf = thermal_print.render_pdf(
            SAMPLE_DOCUMENT,
            now=datetime(2026, 9, 28, 20, 30, tzinfo=ZoneInfo("Asia/Seoul")),
        )

        reader = PdfReader(io.BytesIO(pdf))
        width = float(reader.pages[0].mediabox.width)
        height = float(reader.pages[0].mediabox.height)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertAlmostEqual(width, 80 / 25.4 * 72, places=1)
        self.assertGreater(height, 65 / 25.4 * 72)
        self.assertLessEqual(height, 2_000 / 25.4 * 72)

    def test_event_receipt_uses_compact_kst_title_memo_layout(self) -> None:
        printed_at = datetime(2026, 9, 30, 8, 47, tzinfo=ZoneInfo("Asia/Seoul"))
        document = thermal_print.normalize_document({
            "version": 1,
            "kind": "event",
            "title": "꿈꾸는 농부 캠핑장",
            "subtitle": "2026-10-03 토 15:00 - 2026-10-04 일 11:00 KST",
            "body": "메모",
        })

        ops = thermal_print._document_ops(document, printed_at)
        text = [str(op["text"]) for op in ops if op["type"] == "text"]

        self.assertEqual(text, [
            "KaosGDD",
            "Event 2026-10-03 토 15:00 - 2026-10-04 일 11:00 KST",
            "꿈꾸는 농부 캠핑장",
            "메모",
            "Printed 2026-09-30 수 08:47 KST",
        ])
        self.assertEqual(sum(op["type"] == "rule" for op in ops), 3)

    def test_rejects_unknown_kinds_and_unbounded_item_lists(self) -> None:
        with self.assertRaisesRegex(thermal_print.ThermalPrintError, "invalid_print_kind"):
            thermal_print.normalize_document({"kind": "shell", "title": "No"})

        oversized = {
            "kind": "tasks",
            "title": "Tasks",
            "sections": [{"items": [{"title": str(index)} for index in range(241)]}],
        }
        with self.assertRaisesRegex(thermal_print.ThermalPrintError, "too_many_print_items"):
            thermal_print.normalize_document(oversized)

    def test_destinations_report_ready_without_exposing_url_or_token(self) -> None:
        env = {
            "THERMAL_PRINT_HOME_URL": "http://h4.internal:8100",
            "THERMAL_PRINT_HOME_TOKEN": "home-secret",
            "THERMAL_PRINT_HOME_LABEL": "Home",
        }

        def urlopen(request, **_kwargs):
            self.assertEqual(request.get_header("Authorization"), "Bearer home-secret")
            return FakeResponse(json.dumps({"status": "ready", "mode": "cups", "ready": True}).encode())

        payload = thermal_print.destinations_payload(env=env, urlopen=urlopen)

        self.assertEqual(payload["destinations"], [{
            "id": "home",
            "label": "Home",
            "configured": True,
            "available": True,
            "status": "ready",
            "mode": "cups",
        }])
        self.assertNotIn("url", payload["destinations"][0])
        self.assertNotIn("token", payload["destinations"][0])

    def test_office_choice_appears_only_after_its_connector_url_is_added(self) -> None:
        hidden = thermal_print.destinations_payload(
            env={"THERMAL_PRINT_OFFICE_TOKEN": "future-secret"},
            urlopen=lambda *_args, **_kwargs: self.fail("unconfigured destinations must not be probed"),
        )
        self.assertEqual([item["id"] for item in hidden["destinations"]], ["home"])

        visible = thermal_print.destinations_payload(
            env={"THERMAL_PRINT_OFFICE_URL": "http://office.internal:8100"},
            urlopen=lambda *_args, **_kwargs: self.fail("missing-token destinations must not be probed"),
        )
        self.assertEqual([item["id"] for item in visible["destinations"]], ["home", "office"])
        self.assertEqual(visible["destinations"][1]["status"], "missing_token")

    def test_submit_renders_then_relays_bounded_pdf(self) -> None:
        env = {
            "THERMAL_PRINT_HOME_URL": "http://h4.internal:8100",
            "THERMAL_PRINT_HOME_TOKEN": "home-secret",
        }
        requests = []

        def urlopen(request, **_kwargs):
            requests.append(request)
            if request.full_url.endswith("/health"):
                return FakeResponse(b'{"status":"ready","mode":"cups","ready":true}')
            payload = json.loads(request.data.decode("utf-8"))
            self.assertTrue(base64.b64decode(payload["pdfBase64"]).startswith(b"%PDF-"))
            self.assertEqual(len(payload["pdfSha256"]), 64)
            return FakeResponse(json.dumps({"jobId": payload["jobId"], "status": "submitted", "printerJobId": "receipt-7"}).encode())

        result = thermal_print.submit_payload(
            {"destinationId": "home", "document": SAMPLE_DOCUMENT},
            env=env,
            urlopen=urlopen,
            now=datetime(2026, 9, 28, 20, 30, tzinfo=ZoneInfo("Asia/Seoul")),
        )

        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["printerJobId"], "receipt-7")
        self.assertEqual([request.full_url.rsplit("/", 1)[-1] for request in requests], ["health", "jobs"])

    def test_unready_connector_never_accepts_a_job(self) -> None:
        env = {
            "THERMAL_PRINT_HOME_URL": "http://h4.internal:8100",
            "THERMAL_PRINT_HOME_TOKEN": "home-secret",
        }

        with self.assertRaisesRegex(thermal_print.ThermalPrintError, "printer_not_ready"):
            thermal_print.submit_payload(
                {"destinationId": "home", "document": SAMPLE_DOCUMENT},
                env=env,
                urlopen=lambda *_args, **_kwargs: FakeResponse(b'{"status":"awaiting_printer","ready":false}'),
            )


class ThermalPrintApiTests(unittest.TestCase):
    def test_destinations_are_personal_only(self) -> None:
        handler = CaptureHandler("/api/thermal-print/destinations", {"Host": "family.kaosgdd.net"})
        with (
            mock.patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("family", "family@example.com")),
            mock.patch.object(api.thermal_print, "destinations_payload") as read_destinations,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 404)
        read_destinations.assert_not_called()

    def test_preview_returns_private_inline_pdf(self) -> None:
        body = json.dumps({"document": SAMPLE_DOCUMENT}, ensure_ascii=False).encode("utf-8")
        handler = CaptureHandler("/api/thermal-print/preview", {"Host": "kaosgdd.net"}, body)
        with (
            mock.patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            mock.patch.object(api.thermal_print, "render_pdf", return_value=b"%PDF-preview"),
            mock.patch.object(api.thermal_print, "filename_for_document", return_value="memo-80mm.pdf"),
        ):
            handler.do_POST()

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.response_headers["Content-Type"], "application/pdf")
        self.assertIn("inline", handler.response_headers["Content-Disposition"])
        self.assertEqual(handler.wfile.getvalue(), b"%PDF-preview")

    def test_job_submission_returns_accepted_only_after_connector_accepts(self) -> None:
        request = {"destinationId": "home", "document": SAMPLE_DOCUMENT}
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
        handler = CaptureHandler("/api/thermal-print/jobs", {"Host": "kaosgdd.net"}, body)
        with (
            mock.patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            mock.patch.object(
                api.thermal_print,
                "submit_payload",
                return_value={"ok": True, "status": "submitted", "jobId": "a" * 32},
            ) as submit,
        ):
            handler.do_POST()

        self.assertEqual(handler.status, 202)
        self.assertTrue(json.loads(handler.wfile.getvalue())["ok"])
        submit.assert_called_once_with(request)


if __name__ == "__main__":
    unittest.main()
