from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kaos_governor import api
from kaos_governor.ai_tasks import AITaskArchive, AITaskError
from kaos_governor.official_search import official_health_search_candidates


class FakeHTTPResponse:
    def __init__(self, payload: dict | str, content_type: str = "application/json") -> None:
        self.payload = payload
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:  # type: ignore[no-untyped-def]
        return None

    def read(self, *_args) -> bytes:
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
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


def fake_web_brain_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
    if request.full_url == "http://brain.internal:8099/internal/ai-tasks/official-web/plan":
        assert request.headers["Authorization"] == "Bearer secret"
        body = json.loads(request.data.decode("utf-8"))
        assert body["prompt"] == "공식 자료 찾아서 요약"
        assert "www.kdca.go.kr" in body["allowedDomains"]
        return FakeHTTPResponse(
            {
                "ok": True,
                "plan": {
                    "query": "인플루엔자 접종 계획",
                    "alternateQueries": ["국가 인플루엔자 예방접종"],
                    "preferredDomains": ["kdca.go.kr"],
                    "task": "summary",
                    "language": "ko",
                },
            }
        )
    if request.full_url.startswith("https://www.kdca.go.kr/search.do?"):
        return FakeHTTPResponse(
            '<html><body><a href="/board/notice">26-27절기 국가 인플루엔자 예방접종 계획</a></body></html>',
            "text/html; charset=utf-8",
        )
    if request.full_url == "https://www.kdca.go.kr/board/notice":
        return FakeHTTPResponse(
            "<html><head><title>인플루엔자 계획</title></head><body>국가 인플루엔자 예방접종 공식 본문입니다.</body></html>",
            "text/html; charset=utf-8",
        )
    if request.full_url == "http://brain.internal:8099/internal/ai-tasks/official-web/summarize":
        assert request.headers["Authorization"] == "Bearer secret"
        body = json.loads(request.data.decode("utf-8"))
        assert body["sources"][0]["url"] == "https://www.kdca.go.kr/board/notice"
        return FakeHTTPResponse(
            {
                "ok": True,
                "result": {
                    "title": "공식 자료 요약",
                    "content": "요약 결과",
                    "sources": [{"title": "KDCA", "url": "https://www.kdca.go.kr/board/notice"}],
                    "checkedAt": body["checkedAt"],
                    "model": "kaosbrain-openai",
                },
            }
        )
    raise AssertionError(request.full_url)


class GovernorAITaskTests(unittest.TestCase):
    def test_archive_write_errors_are_reported_as_ai_task_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            with patch.object(Path, "write_text", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(AITaskError, "ai_task_archive_write_failed"):
                    archive.add_preview(
                        kind="official_doc_memo",
                        prompt="요약",
                        source={"title": "공식"},
                        memo={"title": "메모", "content": "본문"},
                    )

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

    def test_preview_official_doc_memo_accepts_pdf_upload_source(self) -> None:
        boundary = "KaosBoundary"
        pdf = b"%PDF-1.7\nbody\n%%EOF"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="prompt"\r\n\r\n'
            "요약해서 메모로\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="sourcePdf"; filename="notice.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + pdf + f"\r\n--{boundary}--\r\n".encode("utf-8")

        class Handler:
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            }
            rfile = BytesIO(body)

        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
                patch.object(api, "extract_official_memo_pdf_text", return_value="PDF extracted text") as extractor,
            ):
                payload = api.preview_official_doc_memo_request_payload(Handler(), archive, urlopen=fake_brain_urlopen)  # type: ignore[arg-type]

            self.assertTrue(payload["ok"])
            extractor.assert_called_once_with("notice.pdf", pdf)
            record = archive.list_records()[0]
            self.assertEqual(record.source["type"], "pdf")
            self.assertEqual(record.source["filename"], "notice.pdf")

    def test_preview_web_ai_task_archives_result_without_memos_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_WEB_BRAIN_URL", ""),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
            ):
                payload = api.preview_web_ai_task_payload(
                    {"prompt": "공식 자료 찾아서 요약"},
                    archive,
                    urlopen=fake_web_brain_urlopen,
                )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["result"]["title"], "공식 자료 요약")  # type: ignore[index]
            records = archive.list_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].kind, "web")
            self.assertEqual(records[0].status, "previewed")
            self.assertEqual(records[0].source["type"], "official_web_search")
            self.assertEqual(records[0].source["plan"]["query"], "인플루엔자 접종 계획")

    def test_hira_insurance_criteria_search_expands_almogran_to_ingredient(self) -> None:
        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            body = request.data.decode("utf-8") if getattr(request, "data", None) else ""
            if request.full_url.startswith("https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrList.do"):
                if "Almotriptan" not in body:
                    return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")
                return FakeHTTPResponse(
                    """<html><body>
                    <a href="#none" onclick="viewInsuAdtCrtr(1, '20130901', '1', '0046', '1'); return false;"
                       title="Almotriptan 경구제 (품명: 알모그란정) 새창으로 열기">Almotriptan 경구제</a>
                    <a href="#none" onclick="viewInsuAdtCrtr(1, '20240901', '3', '0001', '1'); return false;"
                       title="편두통 치료제  새창으로 열기">편두통 치료제</a>
                    </body></html>""",
                    "text/html; charset=utf-8",
                )
            return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")

        candidates = official_health_search_candidates(
            "알모그란정 급여기준",
            preferred_domains=["hira.or.kr"],
            urlopen=fake_urlopen,
        )

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0].host, "www.hira.or.kr")
        self.assertEqual(candidates[0].title, "편두통 치료제")
        self.assertIn("InsuAdtCrtrPopup.do", candidates[0].url)
        self.assertIn("mtgHmeDd=20240901", candidates[0].url)

    def test_search_filters_skip_links(self) -> None:
        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            if request.full_url.startswith("https://www.kdca.go.kr/search.do"):
                return FakeHTTPResponse(
                    '<html><body><a href="/search.do?kwd=인플루엔자">본문 바로가기</a>'
                    '<a href="/board/notice">인플루엔자 예방접종 계획</a></body></html>',
                    "text/html; charset=utf-8",
                )
            return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")

        candidates = official_health_search_candidates("인플루엔자", preferred_domains=["kdca.go.kr"], urlopen=fake_urlopen)

        self.assertEqual([item.title for item in candidates], ["인플루엔자 예방접종 계획"])

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

    def test_pdf_upload_requires_pdf_signature(self) -> None:
        with self.assertRaisesRegex(AITaskError, "ai_task_pdf_signature_invalid"):
            api.extract_official_memo_pdf_text("notice.pdf", b"not a pdf")

    def test_source_hostnames_resolving_to_private_network_are_blocked(self) -> None:
        with patch.object(
            api.socket,
            "getaddrinfo",
            return_value=[(api.socket.AF_INET, api.socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443))],
        ):
            with self.assertRaisesRegex(AITaskError, "ai_task_source_url_blocked"):
                api.fetch_official_source("https://internal.example.test/notice")

    def test_korean_not_found_source_pages_are_rejected(self) -> None:
        def fake_urlopen(_request, timeout=0):  # type: ignore[no-untyped-def]
            return FakeHTTPResponse(
                "<html><head><title>알림메세지</title></head><body>메뉴이(가) 존재 하지 않습니다.</body></html>",
                "text/html; charset=utf-8",
            )

        with self.assertRaisesRegex(AITaskError, "ai_task_source_not_found"):
            api.fetch_official_source("https://www.kdca.go.kr/kdca/284/subview.do", urlopen=fake_urlopen)


if __name__ == "__main__":
    unittest.main()
