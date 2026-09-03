from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kaos_governor import api
from kaos_governor.ai_tasks import AITaskArchive, AITaskError


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:  # type: ignore[no-untyped-def]
        return None

    def read(self, *_args) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def fake_brain_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
    assert request.full_url == "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"
    assert request.headers["Authorization"] == "Bearer secret"
    body = json.loads(request.data.decode("utf-8"))
    assert body["prompt"] == "요약해서 메모로"
    return FakeHTTPResponse(
        {
            "ok": True,
            "memo": {
                "title": "공식문서 요약",
                "content": "# 공식문서 요약\n\n- 핵심",
                "sourceTitle": body["source"]["title"],
                "sourceUrl": body["source"]["url"],
                "checkedAt": body["checkedAt"],
            },
        }
    )


class GovernorAITaskTests(unittest.TestCase):
    def test_preview_official_doc_memo_archives_draft_without_memos_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
            ):
                payload = api.preview_official_doc_memo_payload(
                    {
                        "prompt": "요약해서 메모로",
                        "sourceText": "공식 문서 본문",
                        "sourceUrl": "https://example.go.kr/notice",
                        "sourceTitle": "보도자료",
                    },
                    archive,
                    urlopen=fake_brain_urlopen,
                )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["memo"]["title"], "공식문서 요약")  # type: ignore[index]
            records = archive.list_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, "previewed")
            self.assertNotIn("text", records[0].source)

    def test_complete_marks_archived_task_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            record = archive.add_preview(
                kind="official_doc_memo",
                prompt="요약",
                source={"title": "공식", "url": "https://example.go.kr"},
                memo={"title": "메모", "content": "본문"},
            )

            payload = api.complete_ai_task_payload(record.task_id, {"confirmed": True, "memoName": "memos/123"}, archive)

            self.assertTrue(payload["applied"])
            self.assertEqual(archive.list_records()[0].status, "applied")
            self.assertEqual(archive.list_records()[0].result, {"memoName": "memos/123"})

    def test_source_is_required(self) -> None:
        with self.assertRaisesRegex(AITaskError, "ai_task_source_required"):
            api.official_memo_source_payload({"prompt": "요약"})

    def test_source_hostnames_resolving_to_private_network_are_blocked(self) -> None:
        with patch.object(
            api.socket,
            "getaddrinfo",
            return_value=[(api.socket.AF_INET, api.socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443))],
        ):
            with self.assertRaisesRegex(AITaskError, "ai_task_source_url_blocked"):
                api.fetch_official_source("https://internal.example.test/notice")


if __name__ == "__main__":
    unittest.main()
