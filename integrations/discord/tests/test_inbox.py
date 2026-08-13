from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor.documents import PaperlessConfig, PaperlessDocumentService, PaperlessResult
from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.inbox import DiscordDocumentInbox, rejection_message


class FakePaperless(PaperlessDocumentService):
    def __init__(self):
        super().__init__(
            PaperlessConfig(
                base_url="http://paperless:8000",
                api_token="not-a-real-token",
                max_document_bytes=1024,
            )
        )
        self.submitted = []

    def submit_pdf(self, filename, content, *, title="", source="discord"):
        self.submitted.append((filename, content, title, source))
        return PaperlessResult(
            ok=True,
            task_id=f"task-{len(self.submitted)}",
            filename=filename,
            sha256="hash-" + str(len(content)),
            size_bytes=len(content),
        )


class FakeAttachment:
    def __init__(self, attachment_id=10, filename="scan.pdf", content=b"%PDF-1.7\nbody"):
        self.id = attachment_id
        self.filename = filename
        self._content = content
        self.size = len(content)

    async def read(self, *, use_cached=True):
        return self._content


class DiscordInboxTests(unittest.IsolatedAsyncioTestCase):
    def make_message(self, attachments):
        replies = []

        async def reply(content, **kwargs):
            replies.append((content, kwargs))
            return SimpleNamespace(id=999)

        return SimpleNamespace(
            id=500,
            content="",
            guild=SimpleNamespace(id=100),
            channel=SimpleNamespace(id=300),
            author=SimpleNamespace(id=200, bot=False),
            attachments=attachments,
            reply=AsyncMock(side_effect=reply),
            replies=replies,
        )

    def make_inbox(self, path: Path, paperless=None) -> DiscordDocumentInbox:
        return DiscordDocumentInbox(
            SimpleNamespace(user=SimpleNamespace(id=900)),  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            state_path=path,
            paperless=paperless or FakePaperless(),
        )

    async def test_pdf_upload_is_submitted_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment(filename="../문서.pdf")])

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(len(paperless.submitted), 1)
            self.assertEqual(paperless.submitted[0][0], "문서.pdf")
            self.assertIn("submitted", message.replies[0][0])
            self.assertEqual(inbox.status()["trackedSources"], 1)

    async def test_rejects_non_pdf_without_submitting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment(filename="photo.jpg", content=b"jpg")])

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(paperless.submitted, [])
            self.assertIn("Only PDF", message.replies[0][0])

    async def test_duplicate_source_is_not_submitted_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment()])

            await inbox.handle_message(message)  # type: ignore[arg-type]
            await inbox.handle_message(message)  # type: ignore[arg-type]

            self.assertEqual(len(paperless.submitted), 1)
            self.assertIn("already submitted", message.replies[1][0])

    def test_rejection_message_is_stable(self) -> None:
        self.assertIn("Only PDF", rejection_message(ValueError("pdf_attachment_required")))


if __name__ == "__main__":
    unittest.main()
