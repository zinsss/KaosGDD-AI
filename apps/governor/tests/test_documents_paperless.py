import unittest
from unittest import mock

from kaos_governor.documents import DocumentIntakeError, PaperlessConfig, PaperlessDocumentService


class FakeResponse:
    def __init__(self, status=200, body=b'"task-1"'):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class PaperlessDocumentServiceTests(unittest.TestCase):
    def config(self) -> PaperlessConfig:
        return PaperlessConfig(
            base_url="http://paperless:8000",
            api_token="not-a-real-token",
            max_document_bytes=1024,
        )

    def test_submit_pdf_posts_multipart_document_without_exposing_token(self) -> None:
        urlopen = mock.Mock(return_value=FakeResponse(body=b'{"task_id":"abc"}'))
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        result = service.submit_pdf("../문서.pdf", b"%PDF-1.7\nbody")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://paperless:8000/api/documents/post_document/")
        self.assertEqual(request.get_header("Authorization"), "Token not-a-real-token")
        self.assertIn('name="document"; filename="문서.pdf"'.encode("utf-8"), request.data)
        self.assertIn(b"%PDF-1.7\nbody", request.data)
        self.assertEqual(result.task_id, "abc")
        self.assertEqual(result.filename, "문서.pdf")
        self.assertEqual(result.size_bytes, 13)

    def test_submit_pdf_resolves_and_posts_tags(self) -> None:
        responses = [
            FakeResponse(body=b'{"results":[{"id":7,"name":"medical"}]}'),
            FakeResponse(body=b'{"results":[]}'),
            FakeResponse(body=b'{"id":8,"name":"tax"}'),
            FakeResponse(body=b'{"task_id":"abc"}'),
        ]
        urlopen = mock.Mock(side_effect=responses)
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        service.submit_pdf("scan.pdf", b"%PDF-1.7\nbody", title="Scan", tags=("medical", "tax"))

        methods = [call.args[0].get_method() for call in urlopen.call_args_list]
        self.assertEqual(methods, ["GET", "GET", "POST", "POST"])
        tag_create = urlopen.call_args_list[2].args[0]
        self.assertIn(b'"name": "tax"', tag_create.data)
        self.assertIn(b'"matching_algorithm": 0', tag_create.data)
        self.assertIn(b'"match": ""', tag_create.data)
        upload = urlopen.call_args_list[-1].args[0]
        self.assertIn(b'name="tags"\r\n\r\n7', upload.data)
        self.assertIn(b'name="tags"\r\n\r\n8', upload.data)
        self.assertIn(b'name="title"\r\n\r\nScan', upload.data)

    def test_submit_pdf_posts_configured_owner(self) -> None:
        urlopen = mock.Mock(return_value=FakeResponse(body=b'{"task_id":"abc"}'))
        config = PaperlessConfig(
            base_url="http://paperless:8000",
            api_token="not-a-real-token",
            default_owner_id=3,
        )
        service = PaperlessDocumentService(config, urlopen=urlopen)

        service.submit_pdf("scan.pdf", b"%PDF-1.7\nbody")

        upload = urlopen.call_args.args[0]
        self.assertIn(b'name="owner"\r\n\r\n3', upload.data)

    def test_config_reads_default_owner_from_env(self) -> None:
        config = PaperlessConfig.from_env(
            {
                "PAPERLESS_BASE_URL": "http://paperless:8000",
                "PAPERLESS_API_TOKEN": "token",
                "PAPERLESS_DEFAULT_OWNER_ID": "3",
            }
        )

        self.assertEqual(config.default_owner_id, 3)

    def test_search_documents_uses_paperless_query_endpoint(self) -> None:
        urlopen = mock.Mock(
            side_effect=[
                FakeResponse(
                    body=(
                        b'{"count":1,"results":[{"id":42,"title":"Clinic bill","created":"2026-08-13",'
                        b'"original_file_name":"bill.pdf","correspondent":{"name":"Clinic"}}]}'
                    )
                ),
                FakeResponse(body=b'{"count":212,"results":[]}'),
            ]
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        results = service.search("clinic bill", limit=5)

        request = urlopen.call_args_list[0].args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Token not-a-real-token")
        self.assertIn("/api/documents/?", request.full_url)
        self.assertIn("query=clinic+bill", request.full_url)
        self.assertIn("page_size=5", request.full_url)
        self.assertEqual(results[0].document_id, 42)
        self.assertEqual(results[0].title, "Clinic bill")
        self.assertEqual(results[0].filename, "bill.pdf")
        self.assertEqual(results[0].correspondent, "Clinic")
        self.assertEqual(service.last_result_count, 1)

    def test_task_reads_related_document_ids(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(
                body=b'{"count":1,"results":[{"task_id":"abc","status":"success","related_document_ids":[42]}]}'
            )
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        task = service.task("abc")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIn("/api/tasks/?", request.full_url)
        self.assertIn("task_id=abc", request.full_url)
        self.assertTrue(task.done)
        self.assertTrue(task.success)
        self.assertEqual(task.related_document_ids, (42,))

    def test_search_page_reports_result_and_total_counts(self) -> None:
        urlopen = mock.Mock(
            side_effect=[
                FakeResponse(
                    body=(
                        b'{"count":13,"results":['
                        b'{"id":42,"title":"Clinic bill","created":"2026-08-13",'
                        b'"original_file_name":"bill.pdf","correspondent":{"name":"Clinic"}},'
                        b'{"id":43,"title":"Clinic receipt","created":"2026-08-12",'
                        b'"original_file_name":"receipt.pdf","correspondent_name":"Clinic"}]}'
                    )
                ),
                FakeResponse(body=b'{"count":213,"results":[]}'),
            ]
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        page = service.search_page("clinic", limit=25)

        self.assertEqual(page.query, "clinic")
        self.assertEqual(page.result_count, 13)
        self.assertEqual(page.total_count, 213)
        self.assertEqual(len(page.results), 2)
        self.assertEqual(service.status()["lastResultCount"], 13)

    def test_list_page_browses_recent_documents_without_query(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(
                body=(
                    b'{"count":52,"results":['
                    b'{"id":42,"title":"Clinic bill","created":"2026-08-13",'
                    b'"original_file_name":"bill.pdf","correspondent":{"name":"Clinic"}}]}'
                )
            )
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        page = service.list_page(limit=25, page=2)

        request = urlopen.call_args.args[0]
        self.assertIn("page_size=25", request.full_url)
        self.assertIn("page=2", request.full_url)
        self.assertNotIn("query=", request.full_url)
        self.assertEqual(page.query, "")
        self.assertEqual(page.page, 2)
        self.assertEqual(page.result_count, 52)
        self.assertEqual(page.total_count, 52)
        self.assertEqual(page.results[0].title, "Clinic bill")

    def test_get_document_uses_paperless_detail_endpoint(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(
                body=(
                    b'{"id":42,"title":"Clinic bill","created":"2026-08-13",'
                    b'"original_file_name":"bill.pdf","correspondent":{"name":"Clinic"},'
                    b'"content":"OCR body","tags":[7,8]}'
                )
            )
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        document = service.get(42)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://paperless:8000/api/documents/42/")
        self.assertEqual(request.get_header("Authorization"), "Token not-a-real-token")
        self.assertEqual(document.document_id, 42)
        self.assertEqual(document.title, "Clinic bill")
        self.assertEqual(document.filename, "bill.pdf")
        self.assertEqual(document.correspondent, "Clinic")
        self.assertEqual(document.content, "OCR body")
        self.assertEqual(document.tag_ids, (7, 8))

    def test_update_metadata_resolves_tags_and_patches_document(self) -> None:
        responses = [
            FakeResponse(body=b'{"results":[{"id":7,"name":"medical"}]}'),
            FakeResponse(body=b'{"results":[]}'),
            FakeResponse(body=b'{"id":8,"name":"tax"}'),
            FakeResponse(
                body=(
                    b'{"id":42,"title":"Updated title","created":"2026-08-13",'
                    b'"original_file_name":"bill.pdf","tags":[7,8],"content":"OCR body"}'
                )
            ),
        ]
        urlopen = mock.Mock(side_effect=responses)
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        document = service.update_metadata(42, title=" Updated   title ", tags=("medical", "tax", "medical"))

        self.assertEqual(document.title, "Updated title")
        self.assertEqual(document.tag_ids, (7, 8))
        methods = [call.args[0].get_method() for call in urlopen.call_args_list]
        self.assertEqual(methods, ["GET", "GET", "POST", "PATCH"])
        request = urlopen.call_args_list[-1].args[0]
        self.assertEqual(request.full_url, "http://paperless:8000/api/documents/42/")
        self.assertIn(b'"title": "Updated title"', request.data)
        self.assertIn(b'"tags": [7, 8]', request.data)

    def test_metadata_proposal_reads_document_without_writing(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(
                body=(
                    b'{"id":42,"title":"Clinic bill","created":"2026-08-13",'
                    b'"original_file_name":"bill.pdf","content":"OCR body","tags":[7]}'
                )
            )
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        proposal = service.metadata_proposal(42, title="Updated", tags=("#medical", "tax"))

        self.assertEqual(proposal["proposal"]["oldTitle"], "Clinic bill")
        self.assertEqual(proposal["proposal"]["title"], "Updated")
        self.assertEqual(proposal["proposal"]["tags"], ["medical", "tax"])
        self.assertEqual(urlopen.call_count, 1)

    def test_list_tags_reads_existing_paperless_tags(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(body=b'{"results":[{"id":7,"name":"server"},{"id":8,"name":"Clinic"}]}')
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        tags = service.list_tags()

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIn("/api/tags/?", request.full_url)
        self.assertIn("page_size=200", request.full_url)
        self.assertEqual([tag.as_dict() for tag in tags], [{"id": 7, "name": "server"}, {"id": 8, "name": "Clinic"}])

    def test_existing_tag_names_filters_ai_suggestions_to_current_paperless_tags(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(body=b'{"results":[{"id":7,"name":"server"},{"id":8,"name":"Clinic"}]}')
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        tags = service.existing_tag_names(["#Server", "made-up", "clinic", "server"])

        self.assertEqual(tags, ("server", "Clinic"))

    def test_get_document_rejects_invalid_id_before_network(self) -> None:
        urlopen = mock.Mock()
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        with self.assertRaisesRegex(DocumentIntakeError, "paperless_document_id_invalid"):
            service.get("nope")

        urlopen.assert_not_called()

    def test_rejects_non_pdf_and_oversize_before_network(self) -> None:
        urlopen = mock.Mock()
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        with self.assertRaisesRegex(DocumentIntakeError, "pdf_attachment_required"):
            service.submit_pdf("scan.jpg", b"%PDF-1.7")
        with self.assertRaisesRegex(DocumentIntakeError, "invalid_pdf_signature"):
            service.submit_pdf("scan.pdf", b"not-pdf")
        with self.assertRaisesRegex(DocumentIntakeError, "pdf_size_invalid"):
            service.submit_pdf("scan.pdf", b"%PDF-" + (b"x" * 2048))

        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
