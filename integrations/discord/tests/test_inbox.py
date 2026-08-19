from __future__ import annotations

from pathlib import Path
import hashlib
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor.documents import (
    DocumentIntakeError,
    PaperlessConfig,
    PaperlessDocumentService,
    PaperlessResult,
    PaperlessSearchPage,
    PaperlessSearchResult,
)
from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.inbox import (
    DiscordDocumentInbox,
    InboxRecord,
    PaperlessSearchView,
    attachment_display_filename,
    generated_discord_filename,
    parse_metadata_reply,
    rejection_message,
    render_ocr_pending_message,
    render_ocr_ready_message,
    render_paperless_opened,
    render_processing_message,
    render_submitted_message,
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
    def __init__(
        self,
        attachment_id=10,
        filename="scan.pdf",
        content=b"%PDF-1.7\nbody",
        *,
        title=None,
        url="",
        proxy_url="",
        fail_cached=False,
        fail_uncached=False,
    ):
        self.id = attachment_id
        self.filename = filename
        self.title = title
        self.description = ""
        self.url = url
        self.proxy_url = proxy_url
        self._content = content
        self.size = len(content)
        self.fail_cached = fail_cached
        self.fail_uncached = fail_uncached
        self.read_calls = []

    async def read(self, *, use_cached=True):
        self.read_calls.append(use_cached)
        if use_cached and self.fail_cached:
            import discord

            raise discord.HTTPException(SimpleNamespace(status=415, reason="Unsupported Media Type"), "failed to get asset")
        if not use_cached and self.fail_uncached:
            import discord

            raise discord.HTTPException(SimpleNamespace(status=404, reason="Not Found"), "failed to get asset")
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

    def make_inbox_with_extra_channel(self, path: Path, paperless=None) -> DiscordDocumentInbox:
        return DiscordDocumentInbox(
            self.bot,  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300, 302})),
            channel_id=300,
            extra_channel_ids=frozenset({302}),
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

    async def test_pdf_upload_uses_canonical_attachment_before_cached_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            attachment = FakeAttachment(filename="처방전 대리수령 신청서.pdf", fail_cached=True)
            message = self.make_message([attachment])

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(attachment.read_calls, [False])
            self.assertIn("처방전 대리수령 신청서.pdf", message.replies[0][0])
            self.assertEqual(inbox.status()["pendingCount"], 1)

    async def test_pdf_upload_falls_back_to_cached_attachment_when_canonical_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            attachment = FakeAttachment(filename="scan.pdf", fail_uncached=True)
            message = self.make_message([attachment])

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(attachment.read_calls, [False, True])
            self.assertEqual(inbox.status()["pendingCount"], 1)

    async def test_pdf_upload_uses_discord_attachment_title_for_display_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            attachment = FakeAttachment(
                filename="8f0ea2e73b58ad58.pdf",
                title="처방전 대리수령 신청서.pdf",
            )
            message = self.make_message([attachment])

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(attachment_display_filename(attachment), "처방전 대리수령 신청서.pdf")
            self.assertIn("처방전 대리수령 신청서.pdf", message.replies[0][0])
            self.assertNotIn("8f0ea2e73b58ad58.pdf", message.replies[0][0])

    async def test_pdf_upload_uses_cdn_url_filename_before_generated_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            attachment = FakeAttachment(
                filename="40eeb76102ae4b88.pdf",
                url="https://cdn.discordapp.com/attachments/1/2/%EC%B2%98%EB%B0%A9%EC%A0%84.pdf?ex=x",
            )
            message = self.make_message([attachment])

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(attachment_display_filename(attachment), "처방전.pdf")
            self.assertIn("처방전.pdf", message.replies[0][0])
            self.assertNotIn("40eeb76102ae4b88.pdf", message.replies[0][0])

    async def test_process_as_is_rejects_generated_discord_filename_without_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment(filename="40eeb76102ae4b88.pdf")])

            await inbox.handle_message(message)  # type: ignore[arg-type]
            source_id = next(iter(inbox.state.pending))

            with self.assertRaisesRegex(DocumentIntakeError, "paperless_metadata_required"):
                await inbox.process_pending(source_id)

            self.assertEqual(paperless.submitted, [])
            self.assertTrue(generated_discord_filename("40eeb76102ae4b88.pdf"))

    async def test_process_pending_uses_metadata_title_as_filename_when_discord_filename_is_generated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            message = self.make_message([FakeAttachment(filename="40eeb76102ae4b88.pdf")])

            await inbox.handle_message(message)  # type: ignore[arg-type]
            source_id = next(iter(inbox.state.pending))
            await inbox.process_pending(source_id, title="처방전 대리수령 신청서", tags=("처방전",))

            self.assertEqual(paperless.submitted[0][0], "처방전 대리수령 신청서.pdf")
            self.assertEqual(paperless.submitted[0][2], "처방전 대리수령 신청서")

    async def test_pdf_upload_in_extra_channel_creates_pending_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox_with_extra_channel(Path(temporary) / "inbox.json", paperless)
            extra_channel = SimpleNamespace(id=302)
            message = self.make_message([FakeAttachment(filename="brain.pdf")])
            message.channel = extra_channel

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(paperless.submitted, [])
            self.assertIn("Choose how to process", message.replies[0][0])
            self.assertEqual(inbox.status()["channelIds"], ["300", "302"])
            self.assertEqual(inbox.status()["pendingCount"], 1)

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

    async def test_duplicate_hash_uses_title_when_original_filename_is_generated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paperless = FakePaperless()
            inbox = self.make_inbox(Path(temporary) / "inbox.json", paperless)
            content = b"%PDF-1.7\nbody"
            digest = hashlib.sha256(content).hexdigest()
            source_id = "discord:100:300:1:10"
            inbox.state.sources[source_id] = InboxRecord(
                source_id=source_id,
                sha256=digest,
                filename="40eeb76102ae4b88.pdf",
                task_id="task-1",
                message_id=1,
                title="처방전 대리수령 신청서",
            )
            inbox.state.hashes[digest] = source_id
            message = self.make_message(
                [
                    FakeAttachment(
                        attachment_id=11,
                        filename="40eeb76102ae4b88.pdf",
                        content=content,
                    )
                ]
            )

            self.assertTrue(await inbox.handle_message(message))  # type: ignore[arg-type]

            self.assertIn("처방전 대리수령 신청서.pdf: already submitted", message.replies[0][0])
            self.assertNotIn("40eeb76102ae4b88.pdf", message.replies[0][0])

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

    def test_processing_document_message_mentions_paperless_work(self) -> None:
        content = render_processing_message("처방전.pdf")

        self.assertIn("Processing in Paperless", content)
        self.assertIn("OCR", content)
        self.assertIn("처방전.pdf", content)

    def test_submitted_document_message_mentions_ocr_may_continue(self) -> None:
        content = render_submitted_message(
            InboxRecord(
                source_id="source",
                sha256="hash",
                filename="처방전.pdf",
                task_id="task-1",
                message_id=1,
                title="처방전",
            )
        )

        self.assertIn("submitted", content)
        self.assertIn("OCR may still be running", content)

    def test_ocr_ready_message_includes_kaosai_tag_prompt(self) -> None:
        content = render_ocr_ready_message(
            InboxRecord(
                source_id="source",
                sha256="hash",
                filename="처방전.pdf",
                task_id="task-1",
                message_id=1,
                document_id=42,
                title="처방전",
            ),
            "처방전 대리수령 신청서",
        )

        self.assertIn("OCR ready", content)
        self.assertIn("`42`", content)
        self.assertIn("문서 42 태그 추천", content)

    def test_ocr_pending_message_keeps_task_id_visible(self) -> None:
        content = render_ocr_pending_message(
            InboxRecord(
                source_id="source",
                sha256="hash",
                filename="처방전.pdf",
                task_id="task-1",
                message_id=1,
                title="처방전",
            )
        )

        self.assertIn("OCR is still processing", content)
        self.assertIn("task-1", content)

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
