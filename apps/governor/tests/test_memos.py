import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse

from kaos_governor.memos import (
    MemosConfig,
    MemosConfigurationError,
    MemosError,
    MemosService,
)


class FakeResponse:
    def __init__(self, payload: dict | bytes) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def config(**overrides) -> MemosConfig:
    values = {
        "enabled": True,
        "base_url": "http://memos.internal:5230",
        "access_token": "secret-personal-access-token",
        "creator": "users/zin",
        "timeout_seconds": 10,
        "max_results": 20,
    }
    values.update(overrides)
    return MemosConfig(**values)


class MemosConfigTests(unittest.TestCase):
    def test_disabled_adapter_does_not_require_credentials(self) -> None:
        parsed = MemosConfig.from_env({})
        self.assertFalse(parsed.enabled)

    def test_enabled_adapter_requires_an_explicit_creator_and_token(self) -> None:
        with self.assertRaises(MemosConfigurationError):
            MemosConfig.from_env({"MEMOS_SEARCH_ENABLED": "true", "MEMOS_BASE_URL": "http://memos"})
        with self.assertRaises(MemosConfigurationError):
            MemosConfig.from_env(
                {
                    "MEMOS_SEARCH_ENABLED": "true",
                    "MEMOS_BASE_URL": "http://memos",
                    "MEMOS_ACCESS_TOKEN": "token",
                    "MEMOS_CREATOR": "zin",
                }
            )

    def test_enabled_adapter_parses_a_valid_internal_url(self) -> None:
        parsed = MemosConfig.from_env(
            {
                "MEMOS_SEARCH_ENABLED": "true",
                "MEMOS_BASE_URL": "http://100.64.0.10:5230/",
                "MEMOS_ACCESS_TOKEN": "token",
                "MEMOS_CREATOR": "users/zin",
            }
        )
        self.assertEqual(parsed.base_url, "http://100.64.0.10:5230")

    def test_access_token_can_be_loaded_from_a_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / "memos-token"
            token_file.write_text("file-token\n", encoding="utf-8")
            parsed = MemosConfig.from_env(
                {
                    "MEMOS_SEARCH_ENABLED": "true",
                    "MEMOS_BASE_URL": "http://memos",
                    "MEMOS_ACCESS_TOKEN_FILE": str(token_file),
                    "MEMOS_CREATOR": "users/zin",
                }
            )
        self.assertEqual(parsed.access_token, "file-token")


class MemosServiceTests(unittest.TestCase):
    def test_search_uses_supported_memos_filters_and_returns_snippets(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(
                {
                    "memos": [
                        {
                            "name": "memos/42",
                            "content": "Thermal printer setup and receipt width notes",
                            "tags": ["server", "printing"],
                            "createTime": "2026-08-01T01:02:03Z",
                            "updateTime": "2026-08-02T01:02:03Z",
                            "visibility": "PRIVATE",
                            "pinned": True,
                        }
                    ]
                }
            )

        service = MemosService(config(max_results=25), open_url)
        results = service.search("thermal printer", ["server"], 5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].memo.name, "memos/42")
        self.assertIn("Thermal printer", results[0].snippet)
        request, timeout = requests[0]
        parsed = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(timeout, 10)
        self.assertEqual(query["pageSize"], ["5"])
        self.assertEqual(query["orderBy"], ["pinned desc, create_time desc"])
        self.assertIn('creator == "users/zin"', query["filter"][0])
        self.assertIn('content.contains("thermal")', query["filter"][0])
        self.assertIn('content.contains("printer")', query["filter"][0])
        self.assertNotIn('content.contains("thermal printer")', query["filter"][0])
        self.assertIn('tag in ["server"]', query["filter"][0])
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-personal-access-token")
        self.assertEqual(service.status()["lastResultCount"], 1)

    def test_search_splits_multi_word_query_into_individual_terms(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append(request)
            return FakeResponse({"memos": [], "totalSize": 0})

        service = MemosService(config(max_results=25), open_url)
        service.search_page("rust desk setup", limit=5)

        parsed = urllib.parse.urlsplit(requests[0].full_url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertIn('content.contains("rust")', query["filter"][0])
        self.assertIn('content.contains("desk")', query["filter"][0])
        self.assertIn('content.contains("setup")', query["filter"][0])
        self.assertNotIn('content.contains("rust desk setup")', query["filter"][0])

    def test_search_page_reports_result_and_total_counts(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append(request.full_url)
            if len(requests) == 1:
                return FakeResponse(
                    {
                        "memos": [
                            {"name": "memos/1", "content": "Rustdesk settings"},
                            {"name": "memos/2", "content": "Rustdesk relay"},
                        ],
                        "totalSize": 13,
                    }
                )
            return FakeResponse({"memos": [{"name": "memos/all"}], "totalSize": 213})

        service = MemosService(config(max_results=25), open_url)
        page = service.search_page("rustdesk", limit=25)

        self.assertEqual(page.query, "rustdesk")
        self.assertEqual(page.result_count, 13)
        self.assertEqual(page.total_count, 213)
        self.assertEqual(len(page.results), 2)
        self.assertEqual(service.status()["lastResultCount"], 13)
        self.assertEqual(len(requests), 2)

    def test_search_requires_a_query_or_tag_and_enforces_limits(self) -> None:
        service = MemosService(config(), lambda *_args, **_kwargs: FakeResponse({"memos": []}))
        with self.assertRaisesRegex(ValueError, "memos_query_or_tag_required"):
            service.search()
        with self.assertRaisesRegex(ValueError, "memos_limit_invalid"):
            service.search("memo", limit=21)
        with self.assertRaisesRegex(ValueError, "memos_tag_invalid"):
            service.search(tags=["not valid"])

    def test_get_fetches_the_current_memo_from_memos(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append(request.full_url)
            return FakeResponse({"name": "memos/abc_1", "content": "Current content"})

        memo = MemosService(config(), open_url).get("memos/abc_1")
        self.assertEqual(memo.content, "Current content")
        self.assertEqual(requests, ["http://memos.internal:5230/api/v1/memos/abc_1"])

    def test_create_posts_private_memo_content(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append((request, timeout, json.loads(request.data.decode("utf-8"))))
            return FakeResponse(
                {
                    "name": "memos/new_1",
                    "content": "새 메모\n#태그",
                    "visibility": "PRIVATE",
                }
            )

        service = MemosService(config(), open_url)
        memo = service.create("새 메모\n#태그")

        request, timeout, body = requests[0]
        self.assertEqual(memo.name, "memos/new_1")
        self.assertEqual(request.full_url, "http://memos.internal:5230/api/v1/memos")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-personal-access-token")
        self.assertEqual(body, {"content": "새 메모\n#태그", "visibility": "PRIVATE"})
        self.assertEqual(timeout, 10)
        self.assertTrue(service.status()["lastCreateAt"])

    def test_create_validates_content_before_network(self) -> None:
        service = MemosService(config(), lambda *_args, **_kwargs: self.fail("unexpected call"))
        with self.assertRaisesRegex(ValueError, "memos_content_required"):
            service.create("   ")

    def test_update_patches_memo_content_with_update_mask(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append((request, timeout, json.loads(request.data.decode("utf-8"))))
            return FakeResponse({"name": "memos/abc_1", "content": "Updated memo"})

        service = MemosService(config(), open_url)
        memo = service.update("memos/abc_1", "Updated memo")

        request, timeout, body = requests[0]
        self.assertEqual(memo.content, "Updated memo")
        self.assertEqual(
            request.full_url,
            "http://memos.internal:5230/api/v1/memos/abc_1?updateMask=content",
        )
        self.assertEqual(request.get_method(), "PATCH")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-personal-access-token")
        self.assertEqual(body, {"content": "Updated memo"})
        self.assertEqual(timeout, 10)

    def test_delete_uses_memo_endpoint_and_accepts_empty_response(self) -> None:
        requests = []

        def open_url(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(b"")

        service = MemosService(config(), open_url)
        service.delete("memos/abc_1")

        request, timeout = requests[0]
        self.assertEqual(request.full_url, "http://memos.internal:5230/api/v1/memos/abc_1")
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-personal-access-token")
        self.assertEqual(timeout, 10)
        self.assertEqual(service.status()["lastError"], "")

    def test_update_and_delete_validate_memo_name(self) -> None:
        service = MemosService(config(), lambda *_args, **_kwargs: self.fail("unexpected call"))
        with self.assertRaisesRegex(ValueError, "memos_name_invalid"):
            service.update("../secret", "memo")
        with self.assertRaisesRegex(ValueError, "memos_name_invalid"):
            service.delete("../secret")

    def test_upstream_auth_failures_have_a_stable_non_secret_code(self) -> None:
        def open_url(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        service = MemosService(config(), open_url)
        with self.assertRaises(MemosError) as raised:
            service.search("memo")
        self.assertEqual(raised.exception.code, "memos_upstream_auth_failed")
        self.assertEqual(service.status()["lastError"], "memos_upstream_auth_failed")

    def test_disabled_adapter_never_calls_upstream(self) -> None:
        service = MemosService(config(enabled=False), lambda *_args, **_kwargs: self.fail("unexpected call"))
        with self.assertRaises(MemosError) as raised:
            service.search("memo")
        self.assertEqual(raised.exception.code, "memos_search_disabled")


if __name__ == "__main__":
    unittest.main()
