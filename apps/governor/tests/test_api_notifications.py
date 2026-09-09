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


class NotificationInboxApiTests(unittest.TestCase):
    def test_web_push_proxy_forwards_subscription_without_browser_credentials(self) -> None:
        requests: list[api.urllib.request.Request] = []

        def fake_urlopen(request: api.urllib.request.Request, timeout: float) -> FakeResponse:
            requests.append(request)
            return FakeResponse({"ok": True, "subscription": {"id": "0123456789abcdef01234567"}})

        with patch.object(api, "secret_value", return_value="server-token"):
            result = api.web_push_payload(
                "main",
                "/tools/web-push/subscriptions",
                method="POST",
                payload={"subscription": {"endpoint": "https://web.push.apple.com/value"}},
                urlopen=fake_urlopen,
            )

        self.assertTrue(result["ok"])
        request = requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["Authorization"], "Bearer server-token")
        self.assertNotIn("server-token", request.data.decode("utf-8"))

    def test_family_profile_cannot_use_web_push(self) -> None:
        with self.assertRaisesRegex(api.NotificationInboxAPIError, "main_profile_required"):
            api.web_push_payload("family", "/tools/web-push/config")

    def test_read_proxy_forwards_only_supported_query_and_server_token(self) -> None:
        requests: list[api.urllib.request.Request] = []

        def fake_urlopen(request: api.urllib.request.Request, timeout: float) -> FakeResponse:
            requests.append(request)
            return FakeResponse({"ok": True, "pendingCount": 1, "items": []})

        with patch.object(api, "secret_value", return_value="server-token"):
            result = api.notification_inbox_payload(
                "main",
                "limit=25&includeAcknowledged=true&ignored=value",
                urlopen=fake_urlopen,
            )

        self.assertEqual(result["pendingCount"], 1)
        self.assertIn("/tools/notifications?limit=25&includeAcknowledged=true", requests[0].full_url)
        self.assertNotIn("ignored", requests[0].full_url)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer server-token")

    def test_ack_proxy_posts_authenticated_actor(self) -> None:
        requests: list[api.urllib.request.Request] = []

        def fake_urlopen(request: api.urllib.request.Request, timeout: float) -> FakeResponse:
            requests.append(request)
            return FakeResponse({"ok": True, "item": {"acknowledged": True}})

        with patch.object(api, "secret_value", return_value="server-token"):
            result = api.notification_acknowledge_payload(
                "main",
                "0123456789abcdef01234567",
                "zin@example.com",
                urlopen=fake_urlopen,
            )

        self.assertTrue(result["item"]["acknowledged"])  # type: ignore[index]
        request = requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"actorId": "zin@example.com"})
        self.assertEqual(request.headers["Authorization"], "Bearer server-token")

    def test_handler_requires_personal_access_for_read_and_ack(self) -> None:
        read = CaptureHandler("/api/notifications", {"Host": "kaosgdd.net"})
        acknowledge = CaptureHandler(
            "/api/notifications/0123456789abcdef01234567/acknowledge",
            {"Host": "kaosgdd.net"},
        )

        with patch.object(
            api.memos_relay,
            "verify_cloudflare_access",
            side_effect=api.memos_relay.MemosRelayError(401, "access_identity_missing"),
        ):
            read.do_GET()
            acknowledge.do_POST()

        self.assertEqual(read.status, 401)
        self.assertEqual(acknowledge.status, 401)

    def test_handler_reads_and_acknowledges_for_personal_identity(self) -> None:
        headers = {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified"}
        read = CaptureHandler("/api/notifications?limit=10", headers)
        acknowledge = CaptureHandler(
            "/api/notifications/0123456789abcdef01234567/acknowledge",
            headers,
        )

        with (
            patch.object(
                api.memos_relay,
                "verify_cloudflare_access",
                return_value=("personal", "zin@example.com"),
            ),
            patch.object(api, "notification_inbox_payload", return_value={"ok": True}) as read_payload,
            patch.object(api, "notification_acknowledge_payload", return_value={"ok": True}) as ack_payload,
        ):
            read.do_GET()
            acknowledge.do_POST()

        self.assertEqual(read.status, 200)
        self.assertEqual(acknowledge.status, 200)
        read_payload.assert_called_once_with("main", "limit=10")
        ack_payload.assert_called_once_with(
            "main",
            "0123456789abcdef01234567",
            "zin@example.com",
        )


if __name__ == "__main__":
    unittest.main()
