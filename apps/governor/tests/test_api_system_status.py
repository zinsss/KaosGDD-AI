from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import patch

from kaos_governor import api


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class CaptureHandler(api.Handler):
    def __init__(self, path: str, headers: dict[str, str]) -> None:
        self.path = path
        self.headers = dict(headers)
        self.rfile = BytesIO()
        self.wfile = BytesIO()
        self.status = 0
        self.response_headers: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.response_headers[keyword] = value

    def end_headers(self) -> None:
        return None


class SystemStatusApiTests(unittest.TestCase):
    def test_payload_fetches_internal_brain_tool_with_server_side_token(self) -> None:
        requests: list[api.urllib.request.Request] = []

        def fake_urlopen(request: api.urllib.request.Request, timeout: float) -> FakeResponse:
            requests.append(request)
            self.assertEqual(timeout, api.SYSTEM_STATUS_TIMEOUT_SECONDS)
            return FakeResponse(
                {
                    "date": "2026-09-01",
                    "source": "governor-runtime-health",
                    "status": {
                        "version": "0.6.0",
                        "discordReady": True,
                        "startupComplete": True,
                        "brainTools": {"enabled": True},
                    },
                }
            )

        with (
            patch.object(api, "secret_value", return_value="server-token"),
            patch.object(api, "discord_brain_channel_url", return_value="https://discord.com/channels/1/2"),
        ):
            payload = api.system_status_payload("main", urlopen=fake_urlopen)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["readOnly"])
        self.assertEqual(payload["brainChannelUrl"], "https://discord.com/channels/1/2")
        self.assertEqual(payload["status"]["version"], "0.6.0")  # type: ignore[index]
        self.assertEqual(len(requests), 1)
        self.assertIn("/tools/system/status?profile=main", requests[0].full_url)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer server-token")

    def test_payload_rejects_family_profile_and_missing_token(self) -> None:
        with self.assertRaisesRegex(api.SystemStatusError, "main_profile_required"):
            api.system_status_payload("family")

        with patch.object(api, "secret_value", return_value=""):
            with self.assertRaisesRegex(api.SystemStatusError, "system_status_token_missing"):
                api.system_status_payload("main")

    def test_handler_rejects_non_personal_cloudflare_identity(self) -> None:
        handler = CaptureHandler("/api/system/status", {"Host": "family.kaosgdd.net"})

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("family", "family@example.com")),
            patch.object(api, "system_status_payload", return_value={"ok": True}) as read_status,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 404)
        self.assertEqual(json.loads(handler.wfile.getvalue())["error"], "main_profile_required")
        read_status.assert_not_called()

    def test_handler_returns_status_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/system/status",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "system_status_payload", return_value={"ok": True, "readOnly": True}) as read_status,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue())["readOnly"], True)
        read_status.assert_called_once_with("main")


if __name__ == "__main__":
    unittest.main()
