from pathlib import Path
import tempfile
import unittest

from kaos_governor.mail.naver import (
    NaverMailConfig,
    NaverMailPoller,
    decode_modified_utf7,
    encode_modified_utf7,
    format_sender,
    parse_message,
    unquote_imap,
)


class FakeMailboxServer:
    def __init__(self) -> None:
        root = encode_modified_utf7("각종공문")
        child = encode_modified_utf7("각종공문/영덕군보건소")
        tax = encode_modified_utf7("세무사")
        self.mailboxes = {
            root: {"uidvalidity": "10", "messages": {1: self.message("Existing")}},
            child: {"uidvalidity": "11", "messages": {}},
            tax: {"uidvalidity": "12", "messages": {}},
        }
        self.fetch_specs: list[str] = []
    @staticmethod
    def message(subject: str, *, attachment: bool = False, html_only: bool = False) -> bytes:
        body = (
            'From: "\\"박득수\\"" <sender@example.test>\r\n'
            "To: clinic@example.test\r\n"
            f"Subject: {subject}\r\n"
            "Date: Tue, 11 Aug 2026 06:30:00 +0000\r\n"
            "MIME-Version: 1.0\r\n"
        )
        if attachment:
            body += (
                'Content-Type: multipart/mixed; boundary="boundary"\r\n\r\n'
                "--boundary\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPreview body\r\n"
                "--boundary\r\nContent-Type: application/pdf\r\n"
                "Content-Disposition: attachment; filename=notice.pdf\r\n"
                "Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQ=\r\n--boundary--\r\n"
            )
        elif html_only:
            body += "Content-Type: text/html; charset=utf-8\r\n\r\n<p>Hello <b>there</b></p><script>bad()</script>"
        else:
            body += "Content-Type: text/plain; charset=utf-8\r\n\r\nPreview body"
        return body.encode("utf-8")

    def factory(self, host, port, timeout):
        self.connection = (host, port, timeout)
        self.last_client = FakeIMAP(self)
        return self.last_client


class NaverMailConfigTests(unittest.TestCase):
    def test_password_can_be_loaded_from_a_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            password_file = Path(temporary_directory) / "naver-password"
            password_file.write_text("mail-file-secret\n", encoding="utf-8")
            config = NaverMailConfig.from_env(
                {
                    "MAIL_NAVER_ENABLED": "true",
                    "MAIL_NAVER_USERNAME": "user@example.test",
                    "MAIL_NAVER_PASSWORD_FILE": str(password_file),
                    "MAIL_NAVER_FOLDERS": "세무사",
                }
            )
        self.assertEqual(config.password, "mail-file-secret")


class FakeIMAP:
    def __init__(self, server: FakeMailboxServer) -> None:
        self.server = server
        self.selected = ""
        self.readonly_values: list[bool] = []

    def login(self, username, password):
        return "OK", [b"logged in"]

    def list(self):
        return "OK", [f'(\\HasNoChildren) "/" "{name}"'.encode() for name in self.server.mailboxes]

    def select(self, mailbox, readonly=False):
        self.readonly_values.append(readonly)
        self.selected = unquote_imap(mailbox)
        return "OK", [str(len(self.server.mailboxes[self.selected]["messages"])).encode()]

    def response(self, code):
        return code, [self.server.mailboxes[self.selected]["uidvalidity"].encode()]

    def uid(self, command, *args):
        mailbox = self.server.mailboxes[self.selected]
        if command == "search":
            values = " ".join(str(uid) for uid in sorted(mailbox["messages"]))
            return "OK", [values.encode()]
        if command == "fetch":
            self.last_fetch_spec = args[1]
            self.server.fetch_specs.append(args[1])
            raw = mailbox["messages"][int(args[0])]
            if args[1] == "(BODY.PEEK[HEADER])":
                raw = raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
            return "OK", [(b"message", raw)]
        raise AssertionError(command)

    def close(self):
        return "OK", [b"closed"]

    def logout(self):
        return "BYE", [b"logout"]


def config(state_path: Path) -> NaverMailConfig:
    return NaverMailConfig(
        enabled=True,
        host="imap.naver.com",
        port=993,
        username="user",
        password="password",
        folder_roots=("각종공문", "세무사"),
        state_path=state_path,
        poll_seconds=60,
        timeout_seconds=20,
        max_attachment_bytes=20 * 1024 * 1024,
        preview_characters=2200,
        mark_existing_on_first_run=True,
    )


def target_config(state_path: Path) -> NaverMailConfig:
    return NaverMailConfig(
        enabled=True,
        host="imap.naver.com",
        port=993,
        username="user",
        password="password",
        folder_roots=("세무사", "영덕군보건소"),
        state_path=state_path,
        poll_seconds=60,
        timeout_seconds=20,
        max_attachment_bytes=20 * 1024 * 1024,
        preview_characters=2200,
        mark_existing_on_first_run=True,
    )


class NaverMailTests(unittest.TestCase):
    def test_modified_utf7_round_trip(self) -> None:
        value = "각종공문/하위 폴더 & test"
        self.assertEqual(decode_modified_utf7(encode_modified_utf7(value)), value)

    def test_parses_body_sender_date_and_attachment(self) -> None:
        mail = parse_message(FakeMailboxServer.message("Notice", attachment=True), "각종공문", 2)
        self.assertEqual(mail.sender, "박득수 <sender@example.test>")
        self.assertEqual(mail.received_at, "2026-08-11 15:30 KST")
        self.assertEqual(mail.preview, "Preview body")
        self.assertEqual(mail.attachments[0].filename, "notice.pdf")
        self.assertEqual(mail.attachments[0].content, b"%PDF-1.4")

    def test_html_fallback_omits_script(self) -> None:
        mail = parse_message(FakeMailboxServer.message("HTML", html_only=True), "세무사", 3)
        self.assertEqual(mail.preview, "Hello there")

    def test_first_scan_baselines_and_new_mail_delivers_once_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeMailboxServer()
            poller = NaverMailPoller(config(Path(tmp) / "state.json"), server.factory)
            summaries = []
            attachments = []
            first = poller.scan(lambda mail: summaries.append(mail) or {"messageId": 1}, lambda item: attachments.append(item))
            root = encode_modified_utf7("각종공문")
            server.mailboxes[root]["messages"][2] = server.message("New", attachment=True)
            second = poller.scan(lambda mail: summaries.append(mail) or {"messageId": 2}, lambda item: attachments.append(item))
            third = poller.scan(lambda mail: summaries.append(mail) or {"messageId": 3}, lambda item: attachments.append(item))
        self.assertEqual((first, second, third), (0, 1, 0))
        self.assertEqual([mail.subject for mail in summaries], ["New"])
        self.assertEqual([item.filename for item in attachments], ["notice.pdf"])
        self.assertTrue(all(server.last_client.readonly_values))
        self.assertEqual(server.fetch_specs, ["(BODY.PEEK[])"])

    def test_list_messages_reads_configured_mailboxes_by_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeMailboxServer()
            child = encode_modified_utf7("각종공문/영덕군보건소")
            tax = encode_modified_utf7("세무사")
            server.mailboxes[child]["messages"][2] = server.message("영덕군 안내")
            server.mailboxes[tax]["messages"][3] = server.message("세무사 안내")
            poller = NaverMailPoller(target_config(Path(tmp) / "state.json"), server.factory)

            payload = poller.list_messages(limit=10)

        self.assertEqual(payload["mailboxCount"], 2)
        self.assertEqual(payload["folders"], ["세무사", "영덕군보건소"])
        self.assertEqual(
            [item["subject"] for item in payload["messages"]],
            ["영덕군 안내", "세무사 안내"],
        )
        self.assertTrue(all(server.last_client.readonly_values))
        self.assertEqual(server.fetch_specs, ["(BODY.PEEK[HEADER])", "(BODY.PEEK[HEADER])"])

    def test_progress_prevents_duplicate_summary_after_attachment_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeMailboxServer()
            poller = NaverMailPoller(config(Path(tmp) / "state.json"), server.factory)
            poller.scan(lambda mail: {"messageId": 1}, lambda item: None)
            root = encode_modified_utf7("각종공문")
            server.mailboxes[root]["messages"][2] = server.message("Retry", attachment=True)
            summaries = []
            attempts = []

            def fail_once(item):
                attempts.append(item.filename)
                if len(attempts) == 1:
                    raise OSError("upload failed")

            poller.scan(lambda mail: summaries.append(mail.subject) or {"messageId": 9}, fail_once)
            poller.scan(lambda mail: summaries.append(mail.subject) or {"messageId": 10}, fail_once)
        self.assertEqual(summaries, ["Retry"])
        self.assertEqual(attempts, ["notice.pdf", "notice.pdf"])

    def test_sender_quote_cleanup(self) -> None:
        self.assertEqual(format_sender('"\\"박득수\\"" <mail@example.test>'), "박득수 <mail@example.test>")


if __name__ == "__main__":
    unittest.main()
