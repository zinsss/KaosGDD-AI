from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor.documents import (
    PaperlessConfig,
    PaperlessDocumentService,
    PaperlessResult,
    PaperlessSearchPage,
    PaperlessSearchResult,
)
from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.inbox import (
    DiscordDocumentInbox,
    PaperlessSearchView,
    parse_metadata_reply,
    rejection_message,
    render_paperless_opened,
)


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
        self.searches = []

    def submit_pdf(self, filename, content, *, title="", tags=(), source="discord"):
        self.submitted.append((filename, content, title, tuple(tags), source))
        return PaperlessResult(
            ok=True,
            task_id=f"task-{len(self.submitted)}",
            filename=filename,
            sha256="hash-" + str(len(content)),
            size_bytes=len(content),
        )

    def search(self, query, *, limit=5):
        self.searches.append((query, limit))
        return [PaperlessSearchResult(42, "Clinic bill", "2026-08-13", "bill.pdf", "Clinic")]

    def search_page(self, query, *, limit=5):
        self.searches.append((query, limit))
        return PaperlessSearchPage(
            query,
            (
                PaperlessSearchResult(42, "Clinic bill", "2026-08-13", "bill.pdf", "Clinic"),
                PaperlessSearchResult(43, "Clinic receipt", "2026-08-12", "receipt.pdf", "Clinic"),
            ),
            13,
            213,
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
    def setUp(self) -> None:
        self.channel = SimpleNamespace(id=300, sent=[])

        async def send(content, **kwargs):
            self.channel.sent.append((content, kwargs))
            return SimpleNamespace(id=998)

        self.channel.send = AsyncMock(side_effect=send)
        self.bot = SimpleNamespace(
            user=SimpleNamespace(id=900),
            get_channel=lambda channel_id: self.channel if channel_id == 300 else None,
            fetch_channel=AsyncMock(return_value=self.channel),
            add_view=lambda view, *, message_id=None: self.registered_views.append((view, message_id)),
        )
        self.registered_views = []

    def make_message(self, attachments, *, content=""):
        replies = []

        async def reply(content, **kwargs):
            prompt = SimpleNamespace(id=999, content=content, kwargs=kwargs)
            replies.append((content, kwargs, prompt))
            return prompt

        message = SimpleNamespace(
            id=500,
            content=content,
            guild=SimpleNamespace(id=100),
            channel=self.channel,
            author=SimpleNamespace(id=200, bot=False),
            attachments=attachments,
            reply=AsyncMock(side_effect=reply),
            delete=AsyncMock(),
            replies=replies,
        )
        self.channel.fetch_message = AsyncMock(return_value=message)
        return message

    def make_inbox(self, path: Path, paperless=None) -> DiscordDocumentInbox:
        return DiscordDocumentInbox(
            self.bot,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            state_path=path,
            paperless=paperless or FakePaperless(),
        )

    async def test_pdf_upload_creates_pending_prompt_without_submitting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment(filename="../문서.pdf")])

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(paperless.submitted, [])
            self.assertIn("Choose how to process", message.replies[0][0])
            self.assertIn("view", message.replies[0][1])
            self.assertEqual(inbox.status()["pendingCount"], 1)
            self.assertEqual(inbox.status()["trackedSources"], 0)

    async def test_process_pending_records_completed_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment(filename="../문서.pdf")])

            await inbox.handle_message(message)  # type: ignore[arg-type]
            source_id = next(iter(inbox.state.pending))
            record = await inbox.process_pending(source_id, title="Receipt", tags=("medical", "tax"))

            self.assertEqual(record.filename, "문서.pdf")
            self.assertEqual(paperless.submitted[0][0], "문서.pdf")
            self.assertEqual(paperless.submitted[0][2], "Receipt")
            self.assertEqual(paperless.submitted[0][3], ("medical", "tax"))
            self.assertEqual(inbox.status()["pendingCount"], 0)
            self.assertEqual(inbox.status()["trackedSources"], 1)

    async def test_process_pending_preserves_original_filename_without_kaos_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment(filename="의료기관 보건의료인력.pdf")])

            await inbox.handle_message(message)  # type: ignore[arg-type]
            source_id = next(iter(inbox.state.pending))
            await inbox.process_pending(source_id)

            self.assertEqual(paperless.submitted[0][0], "의료기관 보건의료인력.pdf")
            self.assertFalse(paperless.submitted[0][0].startswith("kaos-"))

    async def test_restore_pending_views_registers_existing_prompt_view(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            state_path = Path(temporary) / "inbox.json"
            inbox = self.make_inbox(state_path, paperless)
            message = self.make_message([FakeAttachment(filename="../문서.pdf")])
            await inbox.handle_message(message)  # type: ignore[arg-type]
            source_id = next(iter(inbox.state.pending))
            pending = inbox.state.pending[source_id]
            prompt = SimpleNamespace(id=pending.prompt_message_id, edit=AsyncMock())
            self.channel.fetch_message = AsyncMock(return_value=prompt)
            self.registered_views = []

            restored = await inbox.restore_pending_views()

            self.assertEqual(restored, 1)
            prompt.edit.assert_awaited_once()
            self.assertEqual(self.registered_views[0][1], pending.prompt_message_id)

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
            source_id = next(iter(inbox.state.pending))
            await inbox.process_pending(source_id)
            await inbox.handle_message(message)  # type: ignore[arg-type]

            self.assertEqual(len(paperless.submitted), 1)
            self.assertIn("already submitted", message.replies[1][0])

    async def test_dotdot_message_searches_paperless_then_deletes_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([], content="..clinic")

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(paperless.submitted, [])
            self.assertEqual(paperless.searches, [("clinic", 25)])
            message.delete.assert_awaited_once()
            self.assertIn("Searched..", self.channel.sent[0][0])
            self.assertIn("## clinic", self.channel.sent[0][0])
            self.assertIn("13 results in 213 documents", self.channel.sent[0][0])
            self.assertIn("view", self.channel.sent[0][1])
            self.assertEqual(self.channel.sent[0][1]["view"]._message.id, 998)
            self.assertEqual(message.replies, [])

    async def test_paperless_search_view_clears_dropdown_on_timeout(self) -> None:
        page = FakePaperless().search_page("clinic", limit=25)
        view = PaperlessSearchView(page, AccessPolicy(100, frozenset({200}), frozenset({300})))
        message = SimpleNamespace(id=123, edit=AsyncMock())
        view.bind_message(message)

        await view.on_timeout()

        message.edit.assert_awaited_once()
        self.assertIsNone(message.edit.await_args.kwargs["view"])

    async def test_dotdot_message_normalizes_multi_term_paperless_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([], content="..rust   desk setup")

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(paperless.searches, [("rust desk setup", 25)])
            self.assertIn("## rust desk setup", self.channel.sent[0][0])

    def test_opened_document_renders_link_and_details(self) -> None:
        content = render_paperless_opened(
            "clinic",
            PaperlessSearchResult(42, "Clinic bill", "2026-08-13T12:30:00Z", "bill.pdf", "Clinic"),
            public_url="https://paperless.example",
        )

        self.assertIn("## Documents search", content)
        self.assertIn("### Clinic bill", content)
        self.assertIn("https://paperless.example/documents/42/details", content)
        self.assertIn("2026-08-13", content)
        self.assertIn("Clinic", content)
        self.assertIn("bill.pdf", content)

    def test_parse_metadata_reply_extracts_title_and_tags(self) -> None:
        self.assertEqual(
            parse_metadata_reply("### Insurance document\n#medical #Tax #의료"),
            ("Insurance document", ("medical", "Tax", "의료")),
        )
        self.assertIsNone(parse_metadata_reply("#tag-only"))

    def test_rejection_message_is_stable(self) -> None:
        self.assertIn("Only PDF", rejection_message(ValueError("pdf_attachment_required")))


if __name__ == "__main__":
    unittest.main()
