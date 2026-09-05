from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from kaos_governor import api
from kaos_governor.ai_tasks import AITaskArchive, AITaskError
from kaos_governor.official_search import allowed_official_health_hosts, official_health_search_candidates
from kaos_governor.textbook_search import search_textbook_sources


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


def fake_general_web_brain_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
    assert request.full_url == "http://brain.internal:8099/internal/ai-tasks/web/preview"
    assert request.headers["Authorization"] == "Bearer secret"
    body = json.loads(request.data.decode("utf-8"))
    assert body["prompt"] == "공식 결과를 바탕으로 일반 웹도 확인"
    return FakeHTTPResponse(
        {
            "ok": True,
            "result": {
                "title": "일반 웹 보조 맥락",
                "content": "일반 웹에서 확인한 보조 내용입니다.",
                "sources": [{"title": "Supplemental", "url": "https://example.com/context"}],
                "checkedAt": body["checkedAt"],
                "model": "kaosbrain-openai-web",
            },
        }
    )


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

    def test_textbook_search_expands_korean_condition_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            index_path = Path(temporary_directory) / "harrison-test.sqlite"
            conn = sqlite3.connect(index_path)
            try:
                conn.execute("CREATE TABLE pages (id INTEGER PRIMARY KEY, page INTEGER NOT NULL, text TEXT NOT NULL)")
                conn.execute("CREATE VIRTUAL TABLE pages_fts USING fts5(text)")
                text = "Restless legs syndrome is discussed here with clinical evaluation and treatment options."
                conn.execute("INSERT INTO pages (id, page, text) VALUES (1, 123, ?)", (text,))
                conn.execute("INSERT INTO pages_fts (rowid, text) VALUES (1, ?)", (text,))
                conn.commit()
            finally:
                conn.close()

            sources = search_textbook_sources("하지불안증후군 치료 옵션", index_path=index_path)

        self.assertEqual(sources[0]["citation"], "Harrison 22e, p. 123")
        self.assertIn("Restless legs syndrome", sources[0]["excerpt"])

    def test_web_ai_task_sends_textbook_background_to_brain(self) -> None:
        textbook_source = {
            "title": "Harrison p. 123",
            "book": "Harrison's Principles of Internal Medicine",
            "edition": "22e",
            "page": 123,
            "citation": "Harrison 22e, p. 123",
            "excerpt": "Restless legs syndrome background.",
        }

        def fake_textbook_web_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            if request.full_url == "http://brain.internal:8099/internal/ai-tasks/official-web/plan":
                return FakeHTTPResponse(
                    {
                        "ok": True,
                        "plan": {
                            "query": "하지불안증후군 치료 옵션",
                            "alternateQueries": ["restless legs syndrome treatment guideline"],
                            "preferredDomains": ["pubmed.ncbi.nlm.nih.gov"],
                            "task": "treatment_options",
                            "language": "ko",
                        },
                    }
                )
            if request.full_url.startswith("https://health.kr/"):
                return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")
            if request.full_url.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
                return FakeHTTPResponse(
                    '<html><body><a href="/39324694/">Restless legs syndrome treatment guideline</a></body></html>',
                    "text/html; charset=utf-8",
                )
            if request.full_url == "https://pubmed.ncbi.nlm.nih.gov/39324694/":
                return FakeHTTPResponse("<html><body>Restless legs syndrome guideline abstract.</body></html>", "text/html; charset=utf-8")
            if request.full_url.startswith("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"):
                return FakeHTTPResponse(
                    "<PubmedArticleSet><PubmedArticle><MedlineCitation><Article><ArticleTitle>Restless legs syndrome treatment guideline</ArticleTitle><Abstract><AbstractText>Guideline abstract.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>",
                    "text/xml; charset=utf-8",
                )
            if request.full_url == "http://brain.internal:8099/internal/ai-tasks/official-web/summarize":
                body = json.loads(request.data.decode("utf-8"))
                self.assertEqual(body["textbookSources"][0]["citation"], "Harrison 22e, p. 123")
                return FakeHTTPResponse(
                    {
                        "ok": True,
                        "result": {
                            "title": "치료 옵션 요약",
                            "content": "요약",
                            "sources": [{"title": "PubMed", "url": "https://pubmed.ncbi.nlm.nih.gov/39324694/"}],
                            "checkedAt": body["checkedAt"],
                            "model": "kaosbrain-openai",
                        },
                    }
                )
            raise AssertionError(request.full_url)

        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_WEB_BRAIN_URL", ""),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
                patch.object(api, "search_textbook_sources", return_value=[textbook_source]),
            ):
                payload = api.preview_web_ai_task_payload(
                    {"prompt": "하지불안증후군 치료 옵션"},
                    archive,
                    urlopen=fake_textbook_web_urlopen,
                )

            self.assertTrue(payload["ok"])
            self.assertEqual(archive.list_records()[0].source["textbookSources"][0]["citation"], "Harrison 22e, p. 123")
            self.assertEqual(payload["task"]["source"]["textbookSources"][0]["citation"], "Harrison 22e, p. 123")  # type: ignore[index]

    def test_preview_general_web_ai_task_uses_general_brain_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_WEB_BRAIN_URL", ""),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
            ):
                payload = api.preview_general_web_ai_task_payload(
                    {"prompt": "공식 결과를 바탕으로 일반 웹도 확인"},
                    archive,
                    urlopen=fake_general_web_brain_urlopen,
                )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["result"]["title"], "일반 웹 보조 맥락")  # type: ignore[index]
            records = archive.list_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].kind, "general_web")
            self.assertEqual(records[0].status, "previewed")
            self.assertEqual(records[0].source["type"], "general_web_search")
            self.assertEqual(records[0].source["sources"][0]["url"], "https://example.com/context")

    def test_preview_general_web_ai_task_archives_web_search_failure(self) -> None:
        attempts = 0

        def fake_failing_general_web_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            nonlocal attempts
            attempts += 1
            payload = json.dumps({"ok": False, "error": "kaosbrain_web_search_unavailable"}).encode("utf-8")
            raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, BytesIO(payload))

        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_WEB_BRAIN_URL", ""),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
            ):
                payload = api.preview_general_web_ai_task_payload(
                    {"prompt": "공식 결과를 바탕으로 일반 웹도 확인"},
                    archive,
                    urlopen=fake_failing_general_web_urlopen,
                )

            self.assertTrue(payload["ok"])
            self.assertEqual(attempts, 2)
            self.assertEqual(payload["task"]["status"], "failed")  # type: ignore[index]
            self.assertEqual(payload["task"]["error"], "kaosbrain_web_search_unavailable")  # type: ignore[index]
            records = archive.list_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].kind, "general_web")
            self.assertEqual(records[0].status, "failed")
            self.assertEqual(records[0].error, "kaosbrain_web_search_unavailable")

    def test_start_ai_task_returns_running_record_before_worker_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            payload = api.start_ai_task_payload(
                {"prompt": "공식 자료 찾아서 요약"},
                archive,
                start_worker=False,
                urlopen=fake_web_brain_urlopen,
            )

            self.assertEqual(payload["task"]["status"], "running")  # type: ignore[index]
            self.assertEqual(archive.list_records()[0].status, "running")

            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_WEB_BRAIN_URL", ""),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
            ):
                api.run_ai_task_worker(
                    payload["task"]["id"],  # type: ignore[index]
                    {"prompt": "공식 자료 찾아서 요약"},
                    source_task=False,
                    archive=archive,
                    urlopen=fake_web_brain_urlopen,
                )

            record = archive.list_records()[0]
            self.assertEqual(record.status, "previewed")
            self.assertEqual(record.result["title"], "공식 자료 요약")

    def test_ai_task_worker_archives_failure_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            record = archive.add_running(kind="official_doc_memo", prompt="요약", source={"type": "text"})

            api.run_ai_task_worker(
                record.task_id,
                {"prompt": "요약", "sourceText": "공식 문서"},
                source_task=True,
                archive=archive,
                urlopen=fake_brain_urlopen,
            )

            failed = archive.list_records()[0]
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.error, "ai_task_brain_not_configured")

    def test_official_web_brain_call_retries_transient_http_errors(self) -> None:
        attempts = 0

        def fake_retry_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                payload = json.dumps({"ok": False, "error": "kaosbrain_official_web_summary_unavailable"}).encode("utf-8")
                raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, BytesIO(payload))
            return FakeHTTPResponse(
                {
                    "ok": True,
                    "result": {
                        "title": "요약",
                        "content": "본문",
                        "sources": [{"title": "KDCA", "url": "https://www.kdca.go.kr/notice"}],
                    },
                }
            )

        with (
            patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
            patch.object(api, "AI_TASKS_WEB_BRAIN_URL", ""),
            patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
        ):
            result = api.call_ai_task_official_web_brain(
                "summarize",
                {"prompt": "요약", "sources": [{"title": "KDCA", "url": "https://www.kdca.go.kr/notice"}]},
                urlopen=fake_retry_urlopen,
            )

        self.assertEqual(attempts, 2)
        self.assertEqual(result["title"], "요약")

    def test_ai_task_worker_preserves_sources_when_official_summary_fails(self) -> None:
        def fake_summary_failure_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            if request.full_url == "http://brain.internal:8099/internal/ai-tasks/official-web/plan":
                return FakeHTTPResponse(
                    {
                        "ok": True,
                        "plan": {
                            "query": "BPPV 치료 옵션",
                            "alternateQueries": ["benign paroxysmal positional vertigo treatment guideline"],
                            "preferredDomains": ["kdca.go.kr"],
                            "task": "treatment_options",
                            "language": "ko",
                        },
                    }
                )
            if request.full_url.startswith("https://www.kdca.go.kr/search.do?"):
                return FakeHTTPResponse('<html><body><a href="/board/bppv">BPPV 치료 지침</a></body></html>', "text/html; charset=utf-8")
            if request.full_url == "https://www.kdca.go.kr/board/bppv":
                return FakeHTTPResponse("<html><body>BPPV treatment source text</body></html>", "text/html; charset=utf-8")
            if request.full_url == "http://brain.internal:8099/internal/ai-tasks/official-web/summarize":
                payload = json.dumps({"ok": False, "error": "kaosbrain_official_web_summary_unavailable"}).encode("utf-8")
                raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, BytesIO(payload))
            raise AssertionError(request.full_url)

        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = AITaskArchive(Path(temporary_directory) / "ai-tasks.json")
            record = archive.add_running(kind="web", prompt="BPPV 치료 옵션", source={"type": "official_web_search"})
            with (
                patch.object(api, "AI_TASKS_BRAIN_URL", "http://brain.internal:8099/internal/ai-tasks/official-doc-memo/preview"),
                patch.object(api, "AI_TASKS_WEB_BRAIN_URL", ""),
                patch.object(api, "AI_TASKS_BRAIN_TOKEN", "secret"),
            ):
                api.run_ai_task_worker(
                    record.task_id,
                    {"prompt": "BPPV 치료 옵션"},
                    source_task=False,
                    archive=archive,
                    urlopen=fake_summary_failure_urlopen,
                )

            failed = archive.list_records()[0]
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.error, "kaosbrain_official_web_summary_unavailable")
            self.assertEqual(failed.source["plan"]["task"], "treatment_options")
            self.assertEqual(failed.source["sources"][0]["url"], "https://www.kdca.go.kr/board/bppv")
            self.assertIn("Official sources found", failed.result["title"])
            self.assertIn("https://www.kdca.go.kr/board/bppv", failed.result["content"])

    def test_hira_insurance_criteria_search_expands_almogran_to_ingredient(self) -> None:
        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            body = request.data.decode("utf-8") if getattr(request, "data", None) else ""
            if request.full_url.startswith("https://health.kr/"):
                return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")
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

    def test_medicine_benefit_queries_prioritize_hira_without_ai_preference(self) -> None:
        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            body = request.data.decode("utf-8") if getattr(request, "data", None) else ""
            if request.full_url.startswith("https://health.kr/"):
                return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")
            if request.full_url.startswith("https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrList.do"):
                if "Almotriptan" not in body:
                    return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")
                return FakeHTTPResponse(
                    """<html><body>
                    <a href="#none" onclick="viewInsuAdtCrtr(1, '20240901', '3', '0001', '1'); return false;"
                       title="편두통 치료제 새창으로 열기">편두통 치료제</a>
                    </body></html>""",
                    "text/html; charset=utf-8",
                )
            return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")

        candidates = official_health_search_candidates("알모그란정 급여기준", urlopen=fake_urlopen)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source, "건강보험심사평가원 보험인정기준")

    def test_mfds_drug_portal_search_adapter_returns_candidates(self) -> None:
        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            if request.full_url.startswith("https://health.kr/"):
                return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")
            if request.full_url.startswith("https://www.hira.or.kr/"):
                return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")
            if request.full_url.startswith("https://nedrug.mfds.go.kr/searchDrug?"):
                return FakeHTTPResponse(
                    '<html><body><a href="/pbp/CCBBB01/getItemDetail?itemSeq=200100001">알모그란정 제품정보</a></body></html>',
                    "text/html; charset=utf-8",
                )
            return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")

        candidates = official_health_search_candidates(
            "알모그란정 제품정보",
            preferred_domains=["nedrug.mfds.go.kr"],
            urlopen=fake_urlopen,
        )

        self.assertEqual(candidates[0].host, "nedrug.mfds.go.kr")
        self.assertEqual(candidates[0].source, "의약품통합정보시스템")

    def test_treatment_option_queries_expand_korean_conditions_to_guideline_terms(self) -> None:
        searched_terms: list[str] = []

        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            if request.full_url.startswith("https://health.kr/"):
                raise AssertionError("health.kr should not be queried for generic disease treatment options")
            if request.full_url.startswith("https://www.hira.or.kr/"):
                return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")
            if request.full_url.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
                parsed = urllib.parse.urlsplit(request.full_url)
                term = urllib.parse.unquote(urllib.parse.parse_qs(parsed.query).get("term", [""])[0])
                searched_terms.append(term)
                if term == "restless legs syndrome treatment guideline":
                    return FakeHTTPResponse(
                        '<html><body><a href="/39324694/">Restless legs syndrome treatment clinical practice guideline</a></body></html>',
                        "text/html; charset=utf-8",
                    )
            return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")

        candidates = official_health_search_candidates("하지불안증후군 치료 옵션", urlopen=fake_urlopen)

        self.assertIn("restless legs syndrome treatment guideline", searched_terms)
        self.assertEqual(candidates[0].url, "https://pubmed.ncbi.nlm.nih.gov/39324694/")

    def test_treatment_option_queries_search_trusted_guideline_sources(self) -> None:
        urls: list[str] = []

        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)
            if request.full_url.startswith("https://health.kr/"):
                raise AssertionError("health.kr should not be queried for generic disease treatment options")
            if request.full_url.startswith("https://www.hira.or.kr/"):
                return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")
            if request.full_url.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
                return FakeHTTPResponse(
                    '<html><body><a href="/?term=test">Main Content</a><a href="/account/settings/">Account settings</a><a href="/39324694/">Restless legs syndrome treatment clinical practice guideline</a></body></html>',
                    "text/html; charset=utf-8",
                )
            if request.full_url == "https://pubmed.ncbi.nlm.nih.gov/39324694/":
                return FakeHTTPResponse("<html><body>Guideline content</body></html>", "text/html; charset=utf-8")
            return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")

        candidates = official_health_search_candidates(
            "하지불안증후군 치료 옵션",
            alternate_queries=["restless legs syndrome treatment guideline"],
            urlopen=fake_urlopen,
        )

        self.assertIn("pubmed.ncbi.nlm.nih.gov", allowed_official_health_hosts())
        self.assertIn("cks.nice.org.uk", allowed_official_health_hosts())
        self.assertIn("www.ninds.nih.gov", allowed_official_health_hosts())
        self.assertTrue(any(url.startswith("https://pubmed.ncbi.nlm.nih.gov/?term=") for url in urls))
        self.assertEqual(candidates[0].host, "pubmed.ncbi.nlm.nih.gov")
        self.assertEqual(candidates[0].source, "PubMed")

    def test_treatment_options_task_survives_governor_plan_cleanup(self) -> None:
        plan = api._clean_official_web_plan(  # pylint: disable=protected-access
            {
                "query": "하지불안증후군 치료 옵션",
                "alternateQueries": ["restless legs syndrome treatment guideline"],
                "preferredDomains": ["pubmed.ncbi.nlm.nih.gov", "cks.nice.org.uk"],
                "task": "treatment_options",
                "language": "ko",
            },
            prompt="하지불안증후군 치료 옵션",
        )

        self.assertEqual(plan["task"], "treatment_options")
        self.assertEqual(plan["preferredDomains"], ["pubmed.ncbi.nlm.nih.gov", "cks.nice.org.uk"])

    def test_treatment_option_prompt_upgrades_summary_plan(self) -> None:
        plan = api._clean_official_web_plan(  # pylint: disable=protected-access
            {
                "query": "BPPV 치료 옵션",
                "alternateQueries": ["benign paroxysmal positional vertigo treatment guideline"],
                "preferredDomains": ["pubmed.ncbi.nlm.nih.gov"],
                "task": "summary",
                "language": "ko",
            },
            prompt="BPPV 치료 옵션",
        )

        self.assertEqual(plan["task"], "treatment_options")

    def test_pubmed_fetch_uses_eutils_abstract_instead_of_cookie_page(self) -> None:
        urls: list[str] = []

        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            urls.append(request.full_url)
            if request.full_url.startswith("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"):
                return FakeHTTPResponse(
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <PubmedArticleSet><PubmedArticle><MedlineCitation><Article>
                      <Journal><Title>Journal of Vestibular Care</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
                      <ArticleTitle>Benign paroxysmal positional vertigo: effective diagnosis and treatment</ArticleTitle>
                      <PublicationTypeList><PublicationType>Review</PublicationType></PublicationTypeList>
                      <Abstract>
                        <AbstractText>Canalith repositioning is an effective treatment option for posterior canal BPPV.</AbstractText>
                        <AbstractText Label="Diagnosis">Dix-Hallpike testing supports diagnosis when typical nystagmus is present.</AbstractText>
                      </Abstract>
                    </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>""",
                    "application/xml; charset=utf-8",
                )
            if request.full_url == "https://pubmed.ncbi.nlm.nih.gov/36319052/":
                return FakeHTTPResponse(
                    "<html><body>Cookies must be enabled</body></html>",
                    "text/html; charset=utf-8",
                )
            raise AssertionError(request.full_url)

        source = api.fetch_official_source(
            "https://pubmed.ncbi.nlm.nih.gov/36319052/",
            title="BPPV treatment",
            require_allowed_health_host=True,
            urlopen=fake_urlopen,
        )

        self.assertEqual(source["type"], "pubmed")
        self.assertIn("Canalith repositioning", source["text"])
        self.assertIn("Dix-Hallpike", source["text"])
        self.assertNotIn("Cookies must be enabled", source["text"])
        self.assertTrue(urls[0].startswith("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"))

    def test_health_kr_drug_dictionary_expands_brand_for_hira_search(self) -> None:
        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            if request.full_url == "https://health.kr/searchDrug/search_total_result.asp":
                return FakeHTTPResponse('<script>window.csrfToken = "token123";</script>', "text/html; charset=utf-8")
            if request.full_url.startswith("https://health.kr/searchDrug/ajax/ajax_commonSearch.asp"):
                return FakeHTTPResponse(
                    [
                        {
                            "drug_code": "D123",
                            "drug_name": "테스트약정",
                            "drug_enm": "Testdrug Tab.",
                            "list_sunb_name": "Faketriptan Malate 10mg",
                            "effect": "편두통의 급성치료",
                        }
                    ]
                )
            if request.full_url == "https://health.kr/searchDrug/ajax/ajax_result_drug.asp?drug_cd=D123":
                return FakeHTTPResponse(
                    [
                        {
                            "drug_code": "D123",
                            "drug_name": "테스트약정",
                            "sunb": '<a href="/searchIngredient/detail.asp?ingd_code=I123">Faketriptan Malate　가짜트립탄말산염　10mg</a>@',
                            "cls_code_num": "114",
                        }
                    ]
                )
            body = request.data.decode("utf-8") if getattr(request, "data", None) else ""
            if request.full_url.startswith("https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrList.do"):
                if "Faketriptan" not in body:
                    return FakeHTTPResponse("<html><body>검색된 내용이 없습니다.</body></html>", "text/html; charset=utf-8")
                return FakeHTTPResponse(
                    """<html><body>
                    <a href="#none" onclick="viewInsuAdtCrtr(1, '20260101', '7', '0002', '1'); return false;"
                       title="가짜 편두통 치료제 새창으로 열기">가짜 편두통 치료제</a>
                    </body></html>""",
                    "text/html; charset=utf-8",
                )
            return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")

        candidates = official_health_search_candidates(
            "테스트약정 급여기준",
            preferred_domains=["hira.or.kr"],
            urlopen=fake_urlopen,
        )

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source, "건강보험심사평가원 보험인정기준")
        self.assertEqual(candidates[0].title, "가짜 편두통 치료제")
        self.assertIn("mtgHmeDd=20260101", candidates[0].url)

    def test_search_filters_skip_links(self) -> None:
        def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            if request.full_url.startswith("https://health.kr/"):
                return FakeHTTPResponse("<html></html>", "text/html; charset=utf-8")
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
