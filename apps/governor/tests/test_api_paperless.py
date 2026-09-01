from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kaos_governor import api
from kaos_governor.documents import (
    DocumentIntakeStore,
    DocumentIntakeError,
    PaperlessConfig,
    PaperlessDocument,
    PaperlessResult,
    PaperlessSearchPage,
    PaperlessSearchResult,
)


class FakePaperless:
    def __init__(self) -> None:
        self.config = PaperlessConfig(
            base_url="http://paperless.internal:8000",
            api_token="test-token",
            public_url="https://paperless.kaosgdd.net",
        )
        self.calls: list[tuple[object, ...]] = []

    def list_page(self, *, limit: int, page: int) -> PaperlessSearchPage:
        self.calls.append(("list", limit, page))
        result = PaperlessSearchResult(42, "Clinic form", "2026-08-30", "form.pdf", "Hospital")
        return PaperlessSearchPage("", (result,), 26, 26, page, limit)

    def search_page(self, query: object, *, limit: int, page: int) -> PaperlessSearchPage:
        self.calls.append(("search", query, limit, page))
        result = PaperlessSearchResult(7, "Fax report", "2026-08-29", "fax.pdf")
        return PaperlessSearchPage(str(query), (result,), 1, 26, page, limit)

    def get(self, document_id: object) -> PaperlessDocument:
        self.calls.append(("get", document_id))
        return PaperlessDocument(7, "Fax report", "2026-08-29", "fax.pdf", content="OCR text")

    def submit_pdf(
        self,
        filename: str,
        content: bytes,
        *,
        title: str = "",
        tags=(),
        source: str = "discord",
    ) -> PaperlessResult:
        self.calls.append(("submit", filename, title, source, len(content)))
        return PaperlessResult(True, "paperless-task-1", filename, "sha-from-paperless", len(content))


class PaperlessApiTests(unittest.TestCase):
    def test_main_access_uses_verified_cloudflare_identity(self) -> None:
        with patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")) as verify:
            self.assertEqual(api.require_main_access({"Host": "kaosgdd.net"}), "zin@example.com")
        verify.assert_called_once_with({"Host": "kaosgdd.net"})

        with patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("family", "family@example.com")):
            with self.assertRaisesRegex(ValueError, "main_profile_required"):
                api.require_main_access({"Host": "family.kaosgdd.net"})

    def test_browse_returns_normalized_items_and_authoritative_links(self) -> None:
        service = FakePaperless()

        payload = api.paperless_page_payload("page=2&limit=20", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("list", 20, 2)])
        self.assertEqual(payload["totalCount"], 26)
        self.assertEqual(payload["items"][0]["id"], 42)  # type: ignore[index]
        self.assertEqual(
            payload["items"][0]["url"],  # type: ignore[index]
            "https://paperless.kaosgdd.net/documents/42/details",
        )

    def test_search_preserves_query_and_page(self) -> None:
        service = FakePaperless()

        payload = api.paperless_page_payload("query=Fax+report&page=3&limit=10", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("search", "Fax report", 10, 3)])
        self.assertEqual(payload["query"], "Fax report")
        self.assertEqual(payload["resultCount"], 1)

    def test_document_detail_includes_ocr_content_and_link(self) -> None:
        service = FakePaperless()

        payload = api.paperless_document_payload("7", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("get", "7")])
        self.assertEqual(payload["document"]["content"], "OCR text")  # type: ignore[index]
        self.assertEqual(
            payload["document"]["url"],  # type: ignore[index]
            "https://paperless.kaosgdd.net/documents/7/details",
        )

    def test_route_accepts_only_positive_numeric_document_ids(self) -> None:
        self.assertEqual(api.paperless_document_id("/api/paperless/documents/123"), "123")
        self.assertEqual(api.paperless_document_id("/api/paperless/documents/0"), "")
        self.assertEqual(api.paperless_document_id("/api/paperless/documents/abc"), "")

    def test_invalid_query_numbers_are_client_errors(self) -> None:
        with self.assertRaisesRegex(DocumentIntakeError, "paperless_page_invalid"):
            api.paperless_page_payload("page=nope", FakePaperless())  # type: ignore[arg-type]

        self.assertEqual(api.paperless_status_for_error(DocumentIntakeError("paperless_page_invalid")), 400)
        self.assertEqual(api.paperless_status_for_error(DocumentIntakeError("invalid_pdf_signature")), 400)
        self.assertEqual(api.paperless_status_for_error(ValueError("main_profile_required")), 404)

    def test_upload_pdf_submits_to_paperless_and_records_inbox(self) -> None:
        boundary = "KaosBoundary"
        content = b"%PDF-1.7\nbody\n%%EOF"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="title"\r\n\r\n'
            "Clinic upload\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="document"; filename="clinic.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")

        class Handler:
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            }
            rfile = BytesIO(body)

        with tempfile.TemporaryDirectory() as tmp:
            store = DocumentIntakeStore(Path(tmp) / "intake.json")
            service = FakePaperless()
            payload = api.paperless_upload_payload(Handler(), service=service, store=store)  # type: ignore[arg-type]
            inbox = api.paperless_inbox_payload(store)

        self.assertFalse(payload["duplicate"])
        self.assertEqual(payload["item"]["title"], "Clinic upload")  # type: ignore[index]
        self.assertEqual(inbox["items"][0]["taskId"], "paperless-task-1")  # type: ignore[index]
        self.assertEqual(service.calls[-1], ("submit", "clinic.pdf", "Clinic upload", "pwa", len(content)))

    def test_upload_pdf_dedupes_existing_inbox_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DocumentIntakeStore(Path(tmp) / "intake.json")
            content = b"%PDF-1.7\nbody\n%%EOF"
            store.add_submitted(title="Existing", filename="existing.pdf", content=content, task_id="old-task")
            boundary = "KaosBoundary"
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="document"; filename="again.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")

            class Handler:
                headers = {
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body)),
                }
                rfile = BytesIO(body)

            service = FakePaperless()
            payload = api.paperless_upload_payload(Handler(), service=service, store=store)  # type: ignore[arg-type]

        self.assertTrue(payload["duplicate"])
        self.assertEqual(payload["item"]["title"], "Existing")  # type: ignore[index]
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
