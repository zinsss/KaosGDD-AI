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
        upload = urlopen.call_args_list[-1].args[0]
        self.assertIn(b'name="tags"\r\n\r\n7', upload.data)
        self.assertIn(b'name="tags"\r\n\r\n8', upload.data)
        self.assertIn(b'name="title"\r\n\r\nScan', upload.data)

    def test_search_documents_uses_paperless_query_endpoint(self) -> None:
        urlopen = mock.Mock(
            return_value=FakeResponse(
                body=(
                    b'{"results":[{"id":42,"title":"Clinic bill","created":"2026-08-13",'
                    b'"original_file_name":"bill.pdf","correspondent":{"name":"Clinic"}}]}'
                )
            )
        )
        service = PaperlessDocumentService(self.config(), urlopen=urlopen)

        results = service.search("clinic bill", limit=5)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Token not-a-real-token")
        self.assertIn("/api/documents/?", request.full_url)
        self.assertIn("query=clinic+bill", request.full_url)
        self.assertEqual(results[0].document_id, 42)
        self.assertEqual(results[0].title, "Clinic bill")
        self.assertEqual(results[0].filename, "bill.pdf")
        self.assertEqual(results[0].correspondent, "Clinic")

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
