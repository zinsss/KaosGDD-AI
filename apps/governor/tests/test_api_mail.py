from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import Mock, patch

from kaos_governor import api
from kaos_governor.mail.naver import NaverMailError


class FakeMailPoller:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def list_messages(self, *, limit: int = 50) -> dict[str, object]:
        self.calls.append(limit)
        return {
            "mailboxCount": 2,
            "folders": ["INBOX", "세무사"],
            "messages": [
                {
                    "kind": "mail",
                    "direction": "incoming",
                    "mailbox": "INBOX",
                    "uid": 49980,
                    "sender": "Naver <notice@example.com>",
                    "subject": "공지",
                    "preview": "",
                    "receivedAt": "2026-09-01T07:00:00+09:00",
                    "attachmentCount": 1,
                }
            ],
        }


class CaptureHandler(api.Handler):
    def __init__(self, path: str, headers: dict[str, str]) -> None:
        self.path = path
        self.headers = headers
        self.wfile = BytesIO()
        self.status = 0
        self.response_headers: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.response_headers[keyword] = value

    def end_headers(self) -> None:
        return None


class MailApiTests(unittest.TestCase):
    def test_messages_payload_reads_headers_with_bounded_limit(self) -> None:
        poller = FakeMailPoller()

        payload = api.mail_messages_payload("limit=25", poller)  # type: ignore[arg-type]

        self.assertEqual(poller.calls, [25])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["limit"], 25)
        self.assertEqual(payload["mailboxCount"], 2)
        self.assertEqual(payload["messages"][0]["subject"], "공지")  # type: ignore[index]

    def test_limit_is_strictly_bounded(self) -> None:
        for query in ("limit=0", "limit=101", "limit=nope"):
            with self.subTest(query=query), self.assertRaises(NaverMailError):
                api.mail_messages_payload(query, FakeMailPoller())  # type: ignore[arg-type]

        self.assertEqual(api.mail_status_for_error(NaverMailError("mail_limit_invalid")), 400)
        self.assertEqual(api.mail_status_for_error(ValueError("main_profile_required")), 404)
        self.assertEqual(api.mail_status_for_error(api.memos_relay.MemosRelayError(401, "cloudflare_access_required")), 401)
        self.assertEqual(api.mail_status_for_error(NaverMailError("naver_not_configured")), 503)

    def test_list_handler_rejects_non_personal_cloudflare_identity(self) -> None:
        handler = CaptureHandler("/api/mail/messages", {"Host": "family.kaosgdd.net"})
        browse = Mock(return_value={"ok": True, "messages": []})

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("family", "family@example.com")),
            patch.object(api, "mail_messages_payload", browse),
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 404)
        self.assertEqual(json.loads(handler.wfile.getvalue())["error"], "main_profile_required")
        browse.assert_not_called()

    def test_list_handler_returns_messages_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/mail/messages?limit=5",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_messages_payload", return_value={"ok": True, "messages": []}) as browse,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        browse.assert_called_once_with("limit=5")


if __name__ == "__main__":
    unittest.main()
