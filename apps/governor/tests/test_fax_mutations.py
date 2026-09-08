from __future__ import annotations

from datetime import timedelta
import io
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest

from PIL import Image
from pypdf import PdfWriter

from kaos_governor import Actor, DurableGovernorError, GovernorOperations, MemoryDurableGovernorStore
from kaos_governor.fax import FaxError
from kaos_governor.fax_mutations import FaxMutationService, prepare_fax_document


def one_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class FakeFaxService:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            enabled=True,
            transport="connector",
            connector_base_url="https://fax.internal",
            connector_token="configured",
            max_pdf_bytes=2 * 1024 * 1024,
        )
        self.calls = []
        self.failures_remaining = 0

    def submit(self, request, metadata):
        self.calls.append((request, dict(metadata)))
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise FaxError("fax_connector_unavailable")
        return (
            {
                "jobId": "fax-job-1",
                "status": "submitted",
                "destination": request.destination,
                "filename": request.filename,
            },
            True,
        )


class FaxDocumentPreparationTests(unittest.TestCase):
    def test_pdf_is_validated_and_counted(self) -> None:
        prepared = prepare_fax_document(" referral.pdf ", one_page_pdf(), max_bytes=2 * 1024 * 1024)

        self.assertEqual(prepared.filename, "referral.pdf")
        self.assertEqual(prepared.page_count, 1)
        self.assertTrue(prepared.content.startswith(b"%PDF-"))

    def test_image_is_converted_once_in_the_shared_service(self) -> None:
        source = io.BytesIO()
        Image.new("RGBA", (32, 24), (255, 0, 0, 128)).save(source, format="PNG")

        prepared = prepare_fax_document("photo.png", source.getvalue(), max_bytes=2 * 1024 * 1024)

        self.assertEqual(prepared.filename, "photo.pdf")
        self.assertEqual(prepared.page_count, 1)
        self.assertTrue(prepared.content.startswith(b"%PDF-"))

    def test_invalid_document_is_rejected_before_a_proposal(self) -> None:
        with self.assertRaisesRegex(FaxError, "invalid_pdf"):
            prepare_fax_document("bad.pdf", b"%PDF-not-a-document", max_bytes=1024)


class FaxMutationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.stage_root = Path(self.temporary.name) / "fax-proposals"
        self.fax = FakeFaxService()
        self.operations = GovernorOperations(MemoryDurableGovernorStore())
        self.service = FaxMutationService(
            self.fax,  # type: ignore[arg-type]
            self.operations,
            self.stage_root,
            confirmation_ttl=timedelta(minutes=5),
            stage_max_age_seconds=60,
        )
        self.actor = Actor("user", "ios-fax", "personal")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def proposal(self):
        return self.service.propose(
            actor=self.actor,
            idempotency_key="shortcut-run-1",
            destination="02-284-8302",
            filename="referral.pdf",
            content=one_page_pdf(),
        )

    def test_proposal_stages_but_does_not_send(self) -> None:
        proposal = self.proposal()

        self.assertEqual(self.fax.calls, [])
        self.assertEqual(proposal.pending.destination, "022848302")
        self.assertEqual(proposal.pending.page_count, 1)
        staged = self.stage_root / proposal.pending.staged_filename
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.stat().st_mode & 0o777, 0o600)

    def test_exact_approval_submits_once_and_removes_staging(self) -> None:
        proposal = self.proposal()
        confirmation_id = proposal.operation.confirmation.confirmation_id

        result = self.service.approve(confirmation_id, actor=self.actor)
        replay = self.service.approve(confirmation_id, actor=self.actor)

        self.assertEqual(result["fax"]["jobId"], "fax-job-1")
        self.assertFalse(result["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(self.fax.calls), 1)
        self.assertFalse((self.stage_root / proposal.pending.staged_filename).exists())
        self.assertEqual(self.fax.calls[0][1]["source"], "kaosgdd")

    def test_different_actor_cannot_approve(self) -> None:
        proposal = self.proposal()

        with self.assertRaisesRegex(DurableGovernorError, "confirmation_actor_mismatch"):
            self.service.approve(
                proposal.operation.confirmation.confirmation_id,
                actor=Actor("user", "other-user", "personal"),
            )
        self.assertEqual(self.fax.calls, [])

    def test_duplicate_proposal_reuses_confirmation(self) -> None:
        first = self.proposal()
        second = self.proposal()

        self.assertFalse(second.operation.created)
        self.assertEqual(
            first.operation.confirmation.confirmation_id,
            second.operation.confirmation.confirmation_id,
        )

    def test_approved_connector_failure_can_retry_the_same_stable_job(self) -> None:
        proposal = self.proposal()
        confirmation_id = proposal.operation.confirmation.confirmation_id
        self.fax.failures_remaining = 1

        with self.assertRaisesRegex(FaxError, "fax_connector_unavailable"):
            self.service.approve(confirmation_id, actor=self.actor)
        self.assertTrue((self.stage_root / proposal.pending.staged_filename).exists())

        result = self.service.approve(confirmation_id, actor=self.actor)

        self.assertEqual(result["fax"]["jobId"], "fax-job-1")
        self.assertEqual(len(self.fax.calls), 2)
        self.assertEqual(
            self.fax.calls[0][0].source_id,
            self.fax.calls[1][0].source_id,
        )
        self.assertFalse((self.stage_root / proposal.pending.staged_filename).exists())

    def test_stale_staged_files_are_removed(self) -> None:
        self.stage_root.mkdir(parents=True)
        stale = self.stage_root / f"{'a' * 64}.pdf"
        stale.write_bytes(one_page_pdf())
        os.utime(stale, (0, 0))

        self.assertEqual(self.service.cleanup_staged(now=120), 1)
        self.assertFalse(stale.exists())

    def test_expired_confirmation_never_submits(self) -> None:
        service = FaxMutationService(
            self.fax,  # type: ignore[arg-type]
            self.operations,
            self.stage_root,
            confirmation_ttl=timedelta(microseconds=1),
        )
        proposal = service.propose(
            actor=self.actor,
            idempotency_key="expiring-shortcut-run",
            destination="02-284-8302",
            filename="referral.pdf",
            content=one_page_pdf(),
        )
        time.sleep(0.001)

        with self.assertRaisesRegex(DurableGovernorError, "confirmation_expired"):
            service.approve(proposal.operation.confirmation.confirmation_id, actor=self.actor)

        self.assertEqual(self.fax.calls, [])
