from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import Mock, patch

from kaos_governor import api
from kaos_governor.mail import UnreadMail
from kaos_governor.mail.naver import Attachment, MailMessage, NaverMailError


class FakeMailPoller:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def list_messages(self, *, limit: int = 50, folders: tuple[str, ...] | None = None) -> dict[str, object]:
        self.calls.append((limit, folders))
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

    def status(self) -> dict[str, object]:
        self.calls.append("status")
        return {
            "ok": True,
            "folders": ["INBOX", "세무사", "영덕군보건소"],
            "mailboxCount": 3,
            "lastScanAt": "2026-09-04T06:52:29Z",
            "lastError": "",
            "enabled": True,
            "configured": True,
        }

    def pending_count(self, *, folders: tuple[str, ...] | None = None) -> int:
        self.calls.append(("pending_count", folders))
        return 2 if folders == ("영덕군보건소", "세무사") else 3

    def get_message(self, *, mailbox: str, uid: int) -> MailMessage:
        self.calls.append((mailbox, uid))
        return MailMessage(
            mailbox=mailbox,
            uid=uid,
            sender="Naver <notice@example.com>",
            subject="공지",
            preview="본문",
            received_at="2026-09-01 16:00 KST",
            attachments=(Attachment("notice.pdf", "application/pdf", b"%PDF-1.4"),),
        )


class FakeUnreadOrganizer:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def list_unread(self):
        self.calls.append("list_unread")
        return (
            [
                UnreadMail(
                    uid=49980,
                    sender="Inbox <inbox@example.com>",
                    subject="Unread inbox",
                    mailbox_raw="INBOX",
                    mailbox_name="INBOX",
                    uidvalidity="80",
                    received_epoch=1785542400.0,
                ),
                UnreadMail(
                    uid=7,
                    sender="Tax <tax@example.com>",
                    subject="Unread tax",
                    mailbox_raw="세무사",
                    mailbox_name="세무사",
                    uidvalidity="81",
                    received_epoch=1785546000.0,
                ),
            ],
            2,
        )

    def fetch_message(self, *, mailbox_name: str, uid: int) -> MailMessage:
        self.calls.append((mailbox_name, uid))
        return MailMessage(
            mailbox=mailbox_name,
            uid=uid,
            sender="Unread <notice@example.com>",
            subject="Unread detail",
            preview="읽지 않은 본문",
            received_at="2026-09-01 17:00 KST",
            attachments=(Attachment("unread.pdf", "application/pdf", b"%PDF-1.4"),),
        )

    def apply_unread_actions(self, actions: list[dict[str, object]]) -> dict[str, object]:
        self.calls.append(("apply", actions))
        return {"ok": True, "total": len(actions), "applied": {"read": 1, "delete": 1}}


class CaptureHandler(api.Handler):
    def __init__(self, path: str, headers: dict[str, str], body: bytes = b"") -> None:
        self.path = path
        self.headers = dict(headers)
        if body:
            self.headers.setdefault("Content-Length", str(len(body)))
        self.rfile = BytesIO(body)
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

        self.assertEqual(poller.calls, [(25, None)])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["limit"], 25)
        self.assertEqual(payload["mailboxCount"], 2)
        self.assertEqual(payload["messages"][0]["subject"], "공지")  # type: ignore[index]

    def test_messages_payload_passes_requested_folder_scope(self) -> None:
        poller = FakeMailPoller()

        payload = api.mail_messages_payload("limit=25&folder=영덕군보건소&folder=세무사", poller)  # type: ignore[arg-type]

        self.assertEqual(poller.calls, [(25, ("영덕군보건소", "세무사"))])
        self.assertTrue(payload["ok"])

    def test_attention_payload_counts_pending_mail_for_requested_folders_only(self) -> None:
        poller = FakeMailPoller()

        payload = api.mail_attention_payload("folder=영덕군보건소&folder=세무사", poller)  # type: ignore[arg-type]

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["pendingCount"], 2)
        self.assertEqual(payload["folders"], ["영덕군보건소", "세무사"])
        self.assertEqual(payload["mailboxCount"], 3)
        self.assertEqual(poller.calls, ["status", ("pending_count", ("영덕군보건소", "세무사"))])

    def test_limit_is_strictly_bounded(self) -> None:
        for query in ("limit=0", "limit=101", "limit=nope"):
            with self.subTest(query=query), self.assertRaises(NaverMailError):
                api.mail_messages_payload(query, FakeMailPoller())  # type: ignore[arg-type]

        self.assertEqual(api.mail_status_for_error(NaverMailError("mail_limit_invalid")), 400)
        self.assertEqual(api.mail_status_for_error(NaverMailError("mail_uid_invalid")), 400)
        self.assertEqual(api.mail_status_for_error(NaverMailError("mail_mailbox_invalid")), 400)
        self.assertEqual(api.mail_status_for_error(NaverMailError("mail_attachment_invalid")), 400)
        self.assertEqual(api.mail_status_for_error(NaverMailError("mail_message_not_found")), 404)
        self.assertEqual(api.mail_status_for_error(NaverMailError("mail_attachment_not_found")), 404)
        self.assertEqual(api.mail_status_for_error(ValueError("main_profile_required")), 404)
        self.assertEqual(api.mail_status_for_error(api.memos_relay.MemosRelayError(401, "cloudflare_access_required")), 401)
        self.assertEqual(api.mail_status_for_error(NaverMailError("naver_not_configured")), 503)

    def test_message_payload_returns_body_and_attachment_metadata_only(self) -> None:
        poller = FakeMailPoller()

        payload = api.mail_message_payload("49980", "mailbox=INBOX", poller)  # type: ignore[arg-type]

        self.assertEqual(poller.calls, [("INBOX", 49980)])
        message = payload["message"]  # type: ignore[index]
        self.assertEqual(message["preview"], "본문")
        self.assertEqual(message["attachmentCount"], 1)
        self.assertEqual(message["attachments"][0]["index"], 1)
        self.assertEqual(message["attachments"][0]["filename"], "notice.pdf")
        self.assertEqual(message["attachments"][0]["sizeBytes"], 8)
        self.assertNotIn("content", message["attachments"][0])

    def test_message_payload_validates_uid_and_mailbox(self) -> None:
        with self.assertRaisesRegex(NaverMailError, "mail_uid_invalid"):
            api.mail_message_payload("abc", "mailbox=INBOX", FakeMailPoller())  # type: ignore[arg-type]
        with self.assertRaisesRegex(NaverMailError, "mail_mailbox_invalid"):
            api.mail_message_payload("7", "", FakeMailPoller())  # type: ignore[arg-type]

    def test_attachment_payload_returns_selected_attachment_bytes(self) -> None:
        poller = FakeMailPoller()

        content, filename, content_type = api.mail_attachment_payload("49980", "1", "mailbox=INBOX", poller)  # type: ignore[arg-type]

        self.assertEqual(poller.calls, [("INBOX", 49980)])
        self.assertEqual(content, b"%PDF-1.4")
        self.assertEqual(filename, "notice.pdf")
        self.assertEqual(content_type, "application/pdf")

    def test_attachment_payload_validates_index_and_missing_attachment(self) -> None:
        with self.assertRaisesRegex(NaverMailError, "mail_attachment_invalid"):
            api.mail_attachment_payload("49980", "abc", "mailbox=INBOX", FakeMailPoller())  # type: ignore[arg-type]
        with self.assertRaisesRegex(NaverMailError, "mail_attachment_not_found"):
            api.mail_attachment_payload("49980", "2", "mailbox=INBOX", FakeMailPoller())  # type: ignore[arg-type]

    def test_unread_payload_reads_all_incoming_unread_headers(self) -> None:
        organizer = FakeUnreadOrganizer()

        payload = api.mail_unread_payload("limit=5", organizer)  # type: ignore[arg-type]

        self.assertEqual(organizer.calls, ["list_unread"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["limit"], 5)
        self.assertEqual(payload["totalUnread"], 2)
        self.assertEqual(payload["mailboxCount"], 2)
        self.assertEqual(payload["folders"], ["INBOX", "세무사"])
        first = payload["messages"][0]  # type: ignore[index]
        self.assertTrue(first["unread"])
        self.assertEqual(first["mailbox"], "INBOX")
        self.assertEqual(first["uidValidity"], "80")
        self.assertEqual(first["subject"], "Unread inbox")

    def test_unread_message_payload_fetches_read_only_body(self) -> None:
        organizer = FakeUnreadOrganizer()

        payload = api.mail_unread_message_payload("49980", "mailbox=INBOX", organizer)  # type: ignore[arg-type]

        self.assertEqual(organizer.calls, [("INBOX", 49980)])
        message = payload["message"]  # type: ignore[index]
        self.assertTrue(message["unread"])
        self.assertEqual(message["preview"], "읽지 않은 본문")
        self.assertEqual(message["attachmentCount"], 1)

    def test_unread_attachment_payload_returns_selected_attachment_bytes(self) -> None:
        organizer = FakeUnreadOrganizer()

        content, filename, content_type = api.mail_unread_attachment_payload("49980", "1", "mailbox=INBOX", organizer)  # type: ignore[arg-type]

        self.assertEqual(organizer.calls, [("INBOX", 49980)])
        self.assertEqual(content, b"%PDF-1.4")
        self.assertEqual(filename, "unread.pdf")
        self.assertEqual(content_type, "application/pdf")

    def test_unread_actions_payload_applies_read_and_delete_batch(self) -> None:
        organizer = FakeUnreadOrganizer()
        actions = [
            {"mailbox": "INBOX", "uid": 49980, "uidValidity": "80", "action": "read"},
            {"mailbox": "세무사", "uid": 7, "uidValidity": "81", "action": "delete"},
        ]

        payload = api.mail_unread_actions_payload({"items": actions}, organizer)  # type: ignore[arg-type]

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total"], 2)
        self.assertEqual(organizer.calls, [("apply", actions)])

    def test_unread_actions_payload_rejects_missing_items_list(self) -> None:
        with self.assertRaisesRegex(Exception, "mail_batch_invalid"):
            api.mail_unread_actions_payload({}, FakeUnreadOrganizer())  # type: ignore[arg-type]

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

    def test_attention_handler_returns_pending_count_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/mail/attention?folder=영덕군보건소&folder=세무사",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_attention_payload", return_value={"ok": True, "pendingCount": 1}) as attention,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue())["pendingCount"], 1)
        attention.assert_called_once_with("folder=영덕군보건소&folder=세무사")

    def test_detail_handler_returns_message_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/mail/messages/49980?mailbox=INBOX",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_message_payload", return_value={"ok": True, "message": {"uid": 49980}}) as detail,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        detail.assert_called_once_with("49980", "mailbox=INBOX")

    def test_attachment_handler_returns_inline_file_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/mail/messages/49980/attachments/1?mailbox=INBOX",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_attachment_payload", return_value=(b"%PDF-1.4", "notice.pdf", "application/pdf")) as attachment,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.response_headers["Content-Type"], "application/pdf")
        self.assertIn("filename*=UTF-8''notice.pdf", handler.response_headers["Content-Disposition"])
        self.assertEqual(handler.wfile.getvalue(), b"%PDF-1.4")
        attachment.assert_called_once_with("49980", "1", "mailbox=INBOX")

    def test_unread_list_handler_returns_messages_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/mail/unread?limit=5",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_unread_payload", return_value={"ok": True, "messages": []}) as browse,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        browse.assert_called_once_with("limit=5")

    def test_unread_detail_handler_returns_message_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/mail/unread/messages/49980?mailbox=INBOX",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_unread_message_payload", return_value={"ok": True, "message": {"uid": 49980}}) as detail,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        detail.assert_called_once_with("49980", "mailbox=INBOX")

    def test_unread_attachment_handler_returns_inline_file_after_personal_access(self) -> None:
        handler = CaptureHandler(
            "/api/mail/unread/messages/49980/attachments/1?mailbox=INBOX",
            {"Host": "kaosgdd.net", "Cf-Access-Jwt-Assertion": "verified-by-test"},
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_unread_attachment_payload", return_value=(b"%PDF-1.4", "notice.pdf", "application/pdf")) as attachment,
        ):
            handler.do_GET()

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.response_headers["Content-Type"], "application/pdf")
        self.assertEqual(handler.wfile.getvalue(), b"%PDF-1.4")
        attachment.assert_called_once_with("49980", "1", "mailbox=INBOX")

    def test_unread_actions_handler_applies_batch_after_personal_access(self) -> None:
        body = json.dumps(
            {
                "items": [
                    {"mailbox": "INBOX", "uid": 49980, "uidValidity": "80", "action": "read"},
                    {"mailbox": "세무사", "uid": 7, "uidValidity": "81", "action": "delete"},
                ]
            }
        ).encode()
        handler = CaptureHandler(
            "/api/mail/unread/actions",
            {
                "Host": "kaosgdd.net",
                "Cf-Access-Jwt-Assertion": "verified-by-test",
                "Content-Type": "application/json",
            },
            body,
        )

        with (
            patch.object(api.memos_relay, "verify_cloudflare_access", return_value=("personal", "zin@example.com")),
            patch.object(api, "mail_unread_actions_payload", return_value={"ok": True, "total": 2}) as apply_actions,
        ):
            handler.do_POST()

        self.assertEqual(handler.status, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue())["total"], 2)
        apply_actions.assert_called_once()
        self.assertEqual(apply_actions.call_args.args[0]["items"][1]["action"], "delete")


if __name__ == "__main__":
    unittest.main()
