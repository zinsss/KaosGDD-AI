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
