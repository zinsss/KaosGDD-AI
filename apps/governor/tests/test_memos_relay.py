from __future__ import annotations

import base64
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


def load_module(name: str, relative: str):
    test_path = Path(__file__).resolve()
    path = next(
        (
            parent / relative
            for parent in test_path.parents
            if (parent / relative).exists()
        ),
        None,
    )
    if path is None:
        package_name = relative.removeprefix("src/").removesuffix(".py").replace("/", ".")
        return importlib.import_module(package_name)
    src_path = next((parent / "src" for parent in path.parents if (parent / "src").exists()), None)
    if src_path is not None and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{relative} unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MemosRelayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.relay = load_module("kaos_memos_relay", "src/kaos_governor/memos/relay.py")

    def test_profile_is_selected_from_forwarded_host(self) -> None:
        self.assertEqual(
            self.relay.profile_for_headers({"X-Forwarded-Host": "family.kaosgdd.net"}),
            "family",
        )
        self.assertEqual(self.relay.profile_for_headers({"Host": "kaosgdd.net:443"}), "personal")

    def test_unknown_host_is_not_relayed(self) -> None:
        with self.assertRaises(self.relay.MemosRelayError) as raised:
            self.relay.profile_for_headers({"Host": "example.net"})

        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(raised.exception.code, "memos_relay_profile_not_found")

    def test_relay_path_strips_portal_prefix_and_preserves_query(self) -> None:
        self.assertEqual(
            self.relay.relay_path("/api/memos/api/v1/memos?pageSize=20"),
            "/api/v1/memos?pageSize=20",
        )

    def test_route_allow_list_blocks_non_memos_api_paths(self) -> None:
        self.assertTrue(self.relay.route_allowed("GET", "/api/memos/api/v1/auth/me"))
        self.assertTrue(self.relay.route_allowed("GET", "/api/memos/api/v1/memos/abc_123"))
        self.assertTrue(self.relay.route_allowed("PATCH", "/api/memos/api/v1/memos/abc_123?updateMask=content"))
        self.assertFalse(self.relay.route_allowed("GET", "/api/memos/api/v1/users"))
        self.assertFalse(self.relay.route_allowed("POST", "/api/memos/api/v1/auth/signin"))
        self.assertFalse(self.relay.route_allowed("DELETE", "/api/memos/api/v1/memos/abc/attachments/1"))
        self.assertTrue(self.relay.route_allowed("GET", "/api/memos/file/attachments/file_1/scan.pdf"))
        self.assertTrue(self.relay.route_allowed("DELETE", "/api/memos/api/v1/attachments/file_1"))

    def test_upstream_url_uses_internal_memos_origin(self) -> None:
        with patch.dict(os.environ, {"MEMOS_INTERNAL_URL": "http://memos:5230/"}, clear=False):
            self.assertEqual(
                self.relay.upstream_url("/api/v1/auth/me"),
                "http://memos:5230/api/v1/auth/me",
            )

    def test_missing_cloudflare_assertion_is_rejected_before_upstream(self) -> None:
        with self.assertRaises(self.relay.MemosRelayError) as raised:
            self.relay.verify_cloudflare_access({"Host": "family.kaosgdd.net"})

        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.code, "cloudflare_access_required")

    def test_attachment_upload_encodes_binary_for_memos_api(self) -> None:
        response = b'{"name":"attachments/file_1","filename":"scan.pdf","type":"application/pdf","size":"8"}'
        with (
            patch.object(self.relay, "verify_cloudflare_access", return_value=("personal", "me@example.com")),
            patch.object(self.relay, "load_token", return_value="secret-token"),
            patch.object(self.relay, "upstream_request", return_value=(200, "application/json", response)) as upstream,
        ):
            payload = self.relay.upload_attachment(
                {"Host": "kaosgdd.net"},
                filename="scan.pdf",
                content_type="application/pdf",
                content=b"%PDF-1.4",
            )

        self.assertEqual(payload["name"], "attachments/file_1")
        method, path = upstream.call_args.args[:2]
        self.assertEqual((method, path), ("POST", "/api/v1/attachments"))
        sent = __import__("json").loads(upstream.call_args.kwargs["body"])
        self.assertEqual(base64.b64decode(sent["content"]), b"%PDF-1.4")
        self.assertEqual(sent["filename"], "scan.pdf")
        self.assertNotIn("secret-token", upstream.call_args.kwargs["body"].decode("utf-8"))

    def test_attachment_upload_rejects_path_like_filename(self) -> None:
        with patch.object(self.relay, "verify_cloudflare_access", return_value=("personal", "me@example.com")):
            with self.assertRaises(self.relay.MemosRelayError) as raised:
                self.relay.upload_attachment(
                    {"Host": "kaosgdd.net"},
                    filename="../scan.pdf",
                    content_type="application/pdf",
                    content=b"%PDF",
                )

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.code, "memos_attachment_filename_invalid")


if __name__ == "__main__":
    unittest.main()
