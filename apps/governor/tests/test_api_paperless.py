from __future__ import annotations

import json
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
    PaperlessTag,
    PaperlessTask,
)


class FakePaperless:
    def __init__(self) -> None:
        self.config = PaperlessConfig(
            base_url="http://paperless.internal:8000",
            api_token="test-token",
            public_url="https://paperless.kaosgdd.net",
        )
        self.calls: list[tuple[object, ...]] = []
        self.tasks: dict[str, PaperlessTask] = {}
        self.update_calls: list[tuple[object, str, tuple[str, ...]]] = []

    def list_page(self, *, limit: int, page: int, tag_ids=()) -> PaperlessSearchPage:
        self.calls.append(("list", limit, page, tuple(tag_ids)))
        result = PaperlessSearchResult(42, "Clinic form", "2026-08-30", "form.pdf", "Hospital")
        return PaperlessSearchPage("", (result,), 26, 26, page, limit)

    def search_page(self, query: object, *, limit: int, page: int, tag_ids=()) -> PaperlessSearchPage:
        self.calls.append(("search", query, limit, page, tuple(tag_ids)))
        result = PaperlessSearchResult(7, "Fax report", "2026-08-29", "fax.pdf")
        return PaperlessSearchPage(str(query), (result,), 1, 26, page, limit)

    def get(self, document_id: object) -> PaperlessDocument:
        self.calls.append(("get", document_id))
        return PaperlessDocument(7, "Fax report", "2026-08-29", "fax.pdf", content="OCR text", tag_names=("clinic",))

    def list_tags(self) -> tuple[PaperlessTag, ...]:
        self.calls.append(("tags",))
        return (
            PaperlessTag(7, "clinic"),
            PaperlessTag(8, "receipt"),
            PaperlessTag(9, "보험"),
        )

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

    def task(self, task_id: object) -> PaperlessTask:
        self.calls.append(("task", task_id))
        return self.tasks.get(str(task_id)) or PaperlessTask(str(task_id), "PENDING", ())

    def metadata_proposal(self, document_id: object, *, title: str = "", tags=()) -> dict[str, object]:
        self.calls.append(("proposal", document_id, title, tuple(tags)))
        document = self.get(document_id)
        return {
            "document": document.as_dict(),
            "proposal": {
                "id": document.document_id,
                "oldTitle": document.title,
                "title": title or document.title,
                "tags": list(dict.fromkeys(str(tag).strip().lstrip("#") for tag in tags if str(tag).strip())),
            },
        }

    def update_metadata(self, document_id: object, *, title: str, tags=()) -> PaperlessDocument:
        normalized_tags = tuple(str(tag).strip().lstrip("#") for tag in tags if str(tag).strip())
        self.update_calls.append((document_id, title, normalized_tags))
        return PaperlessDocument(int(document_id), title, "2026-08-29", "fax.pdf", content="OCR text", tag_ids=(7, 8), tag_names=normalized_tags)


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

        self.assertEqual(service.calls, [("list", 20, 2, ())])
        self.assertEqual(payload["totalCount"], 26)
        self.assertEqual(payload["items"][0]["id"], 42)  # type: ignore[index]
        self.assertEqual(
            payload["items"][0]["url"],  # type: ignore[index]
            "https://paperless.kaosgdd.net/documents/42/details",
        )

    def test_search_preserves_query_and_page(self) -> None:
        service = FakePaperless()

        payload = api.paperless_page_payload("query=Fax+report&page=3&limit=10", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("search", "Fax report", 10, 3, ())])
        self.assertEqual(payload["query"], "Fax report")
        self.assertEqual(payload["resultCount"], 1)

    def test_search_filters_by_multiple_existing_tags(self) -> None:
        service = FakePaperless()

        payload = api.paperless_page_payload("query=Fax+report&tag=clinic&tag=%EB%B3%B4%ED%97%98&page=1&limit=10", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("tags",), ("search", "Fax report", 10, 1, (7, 9))])
        self.assertEqual(payload["selectedTags"], ["clinic", "보험"])

    def test_missing_tag_filter_returns_no_matches_without_browsing_everything(self) -> None:
        service = FakePaperless()

        payload = api.paperless_page_payload("tag=missing&page=1&limit=10", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("tags",), ("list", 1, 1, ())])
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["resultCount"], 0)
        self.assertEqual(payload["totalCount"], 26)

    def test_tags_payload_lists_existing_paperless_tags(self) -> None:
        service = FakePaperless()

        payload = api.paperless_tags_payload(service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("tags",)])
        self.assertEqual(payload["items"], [{"id": 7, "name": "clinic"}, {"id": 8, "name": "receipt"}, {"id": 9, "name": "보험"}])

    def test_document_detail_includes_ocr_content_and_link(self) -> None:
        service = FakePaperless()

        payload = api.paperless_document_payload("7", service)  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("get", "7")])
        self.assertEqual(payload["document"]["content"], "OCR text")  # type: ignore[index]
        self.assertEqual(payload["document"]["tags"], ["clinic"])  # type: ignore[index]
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
            inbox = api.paperless_inbox_payload(store=store)

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

    def test_inbox_refresh_reconciles_paperless_task_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DocumentIntakeStore(Path(tmp) / "intake.json")
            content = b"%PDF-1.7\nbody\n%%EOF"
            pending = store.add_submitted(title="Pending", filename="pending.pdf", content=content, task_id="pending-task")
            archived = store.add_submitted(title="Done", filename="done.pdf", content=b"%PDF-1.7\n2\n%%EOF", task_id="done-task")
            failed = store.add_submitted(title="Bad", filename="bad.pdf", content=b"%PDF-1.7\n3\n%%EOF", task_id="failed-task")
            service = FakePaperless()
            service.tasks = {
                pending.task_id: PaperlessTask(pending.task_id, "PENDING", ()),
                archived.task_id: PaperlessTask(archived.task_id, "SUCCESS", (88,)),
                failed.task_id: PaperlessTask(failed.task_id, "FAILURE", ()),
            }

            payload = api.paperless_inbox_payload("refresh=1", service=service, store=store)  # type: ignore[arg-type]

        items = {item["id"]: item for item in payload["items"]}  # type: ignore[index]
        self.assertEqual(payload["reconciled"], 2)
        self.assertEqual(items[archived.record_id]["status"], "archived")
        self.assertEqual(items[archived.record_id]["documentId"], 88)
        self.assertEqual(items[archived.record_id]["url"], "https://paperless.kaosgdd.net/documents/88/details")
        self.assertEqual(items[failed.record_id]["status"], "failed")
        self.assertEqual(items[pending.record_id]["status"], "ocr_pending")

    def test_metadata_proposal_requires_confirmation_before_write(self) -> None:
        service = FakePaperless()

        payload = api.paperless_metadata_proposal_payload(
            "7",
            {"title": "Updated title", "tags": ["#clinic", "receipt", "clinic"]},
            service,
        )  # type: ignore[arg-type]

        self.assertTrue(payload["requiresConfirmation"])
        self.assertEqual(payload["proposal"]["title"], "Updated title")  # type: ignore[index]
        self.assertEqual(payload["proposal"]["tags"], ["clinic", "receipt"])  # type: ignore[index]
        self.assertEqual(service.update_calls, [])

    def test_tag_suggestions_use_ai_context_and_existing_paperless_tags(self) -> None:
        service = FakePaperless()
        calls: list[tuple[str, bytes | None]] = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "ok": True,
                        "tags": ["receipt", "made-up", "Clinic", "receipt", "보험"],
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, request.data))
            self.assertEqual(timeout, 20)
            self.assertEqual(request.headers["Authorization"], "Bearer document-token")
            body = json.loads((request.data or b"{}").decode("utf-8"))
            self.assertEqual(body["document"]["title"], "Updated title")
            self.assertEqual(body["document"]["contentExcerpt"], "OCR text")
            self.assertEqual(body["availableTags"][0]["name"], "clinic")
            return Response()

        with patch.object(api, "DOCUMENT_TAG_AI_URL", "http://kaosbrain/internal/documents/tag-suggestions/preview"):
            with patch.object(api, "DOCUMENT_TAG_AI_TOKEN", "document-token"):
                payload = api.paperless_tag_suggestions_payload(
                    "7",
                    {"title": "Updated title"},
                    service,
                    urlopen=fake_urlopen,
                )  # type: ignore[arg-type]

        self.assertEqual(service.calls, [("get", "7"), ("tags",)])
        self.assertEqual(calls[0][0], "http://kaosbrain/internal/documents/tag-suggestions/preview")
        self.assertEqual(payload["source"], "ai")
        self.assertEqual(payload["tags"], ["receipt", "clinic", "보험"])

    def test_tag_suggestions_require_ai_wiring(self) -> None:
        with patch.object(api, "DOCUMENT_TAG_AI_URL", ""):
            with self.assertRaisesRegex(DocumentIntakeError, "paperless_tag_ai_not_configured"):
                api.paperless_tag_suggestions_payload("7", {}, FakePaperless())  # type: ignore[arg-type]

    def test_metadata_apply_requires_confirmed_flag(self) -> None:
        service = FakePaperless()

        with self.assertRaisesRegex(DocumentIntakeError, "paperless_confirmation_required"):
            api.paperless_metadata_apply_payload(
                "7",
                {"title": "Updated title", "tags": ["clinic"], "confirmed": False},
                service,
            )  # type: ignore[arg-type]

        payload = api.paperless_metadata_apply_payload(
            "7",
            {"title": "Updated title", "tags": ["clinic"], "confirmed": True},
            service,
        )  # type: ignore[arg-type]

        self.assertTrue(payload["applied"])
        self.assertEqual(payload["document"]["title"], "Updated title")  # type: ignore[index]
        self.assertEqual(service.update_calls, [("7", "Updated title", ("clinic",))])

    def test_metadata_apply_marks_matching_inbox_record_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DocumentIntakeStore(Path(tmp) / "intake.json")
            record = store.add_submitted(
                title="Fax report",
                filename="fax.pdf",
                content=b"%PDF-1.7\nbody\n%%EOF",
                task_id="done-task",
            )
            store.update_status(record.record_id, status="archived", document_id=7)
            service = FakePaperless()

            payload = api.paperless_metadata_apply_payload(
                "7",
                {"recordId": record.record_id, "title": "Updated title", "tags": ["clinic"], "confirmed": True},
                service,
                store,
            )  # type: ignore[arg-type]
            inbox = api.paperless_inbox_payload(store=store)
            records = store.list_records()

        self.assertTrue(payload["applied"])
        self.assertEqual(records[0].status, "applied")
        self.assertEqual(inbox["items"], [])

    def test_metadata_apply_rejects_mismatched_inbox_record_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DocumentIntakeStore(Path(tmp) / "intake.json")
            record = store.add_submitted(
                title="Fax report",
                filename="fax.pdf",
                content=b"%PDF-1.7\nbody\n%%EOF",
                task_id="done-task",
            )
            store.update_status(record.record_id, status="archived", document_id=8)
            service = FakePaperless()

            with self.assertRaisesRegex(DocumentIntakeError, "paperless_record_mismatch"):
                api.paperless_metadata_apply_payload(
                    "7",
                    {"recordId": record.record_id, "title": "Updated title", "tags": ["clinic"], "confirmed": True},
                    service,
                    store,
                )  # type: ignore[arg-type]

        self.assertEqual(service.update_calls, [])


if __name__ == "__main__":
    unittest.main()
