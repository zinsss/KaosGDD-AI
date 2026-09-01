from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from kaos_governor.mail import MailOrganizerConfig, NaverMailConfig, NaverMailOrganizer
from kaos_governor.mail.naver import KST, encode_modified_utf7, unquote_imap


class FakeOrganizerServer:
    def __init__(self) -> None:
        custom = encode_modified_utf7("청구·결제")
        trash = encode_modified_utf7("Deleted Messages")
        self.mailboxes = {
            "INBOX": {
                "flags": "\\HasNoChildren",
                "uidvalidity": "80",
                "messages": {
                    3: self.message("Older unread", "old@example.test", "Older body", "06:00:00"),
                    7: self.message("Newest unread", "new@example.test", "Newest body", "07:00:00"),
                },
                "seen": set(),
            },
            custom: {
                "flags": "\\HasNoChildren",
                "uidvalidity": "84",
                "messages": {1: self.message("Folder unread", "folder@example.test", "Folder body", "08:00:00")},
                "seen": set(),
            },
            "Sent": {
                "flags": "\\Sent",
                "uidvalidity": "85",
                "messages": {2: self.message("Sent mail", "me@example.test", "Sent", "09:00:00")},
                "seen": set(),
            },
            trash: {
                "flags": "\\Trash",
                "uidvalidity": "86",
                "messages": {},
                "seen": set(),
            },
        }
        self.moved: list[tuple[list[int], str]] = []
        self.fetch_specs: list[str] = []
        self.store_specs: list[tuple[str, str, str]] = []
        self.readonly_values: list[bool] = []

    @staticmethod
    def message(subject: str, sender: str, body: str, time_value: str) -> bytes:
        return (
            f"From: {sender}\r\n"
            "To: clinic@example.test\r\n"
            f"Subject: {subject}\r\n"
            f"Date: Tue, 11 Aug 2026 {time_value} +0000\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            f"{body}"
        ).encode()

    def factory(self, host, port, timeout):
        self.connection = (host, port, timeout)
        return FakeOrganizerIMAP(self)


class FakeOrganizerIMAP:
    def __init__(self, server: FakeOrganizerServer) -> None:
        self.server = server
        self.selected = ""

    def login(self, username, password):
        return "OK", [b"logged in"]

    def list(self):
        rows = [
            f'({data["flags"]}) "/" "{name}"'.encode()
            for name, data in self.server.mailboxes.items()
        ]
        return "OK", rows

    def select(self, mailbox, readonly=False):
        self.selected = unquote_imap(mailbox)
        self.server.readonly_values.append(readonly)
        return "OK", [str(len(self.server.mailboxes[self.selected]["messages"])).encode()]

    def response(self, code):
        return code, [self.server.mailboxes[self.selected]["uidvalidity"].encode()]

    def uid(self, command, *args):
        box = self.server.mailboxes[self.selected]
        if command == "search":
            values = [uid for uid in box["messages"] if uid not in box["seen"]]
            return "OK", [" ".join(str(uid) for uid in sorted(values)).encode()]
        if command == "fetch":
            self.server.fetch_specs.append(args[1])
            return "OK", [(b"message", box["messages"][int(args[0])])]
        if command == "store":
            values = [int(value) for value in str(args[0]).split(",")]
            self.server.store_specs.append((str(args[0]), str(args[1]), str(args[2])))
            box["seen"].update(values)
            return "OK", [b"stored"]
        if command == "MOVE":
            values = [int(value) for value in str(args[0]).split(",")]
            self.server.moved.append((values, str(args[1])))
            return "OK", [b"moved"]
        raise AssertionError((command, args))

    def unselect(self):
        return "OK", [b"unselected"]

    def logout(self):
        return "BYE", [b"logout"]


def organizer(root: Path, server: FakeOrganizerServer) -> NaverMailOrganizer:
    config = MailOrganizerConfig(
        enabled=True,
        state_path=root / "organizer.json",
        max_items=30,
        scheduler_poll_seconds=60,
        trash_folder="Deleted Messages",
        runs_per_day=1,
        first_time="09:00",
        second_time="17:00",
        digest_ttl_days=14,
    )
    naver = NaverMailConfig(
        enabled=True,
        host="imap.naver.com",
        port=993,
        username="user",
        password="password",
        folder_roots=("각종공문", "세무사"),
        state_path=root / "poller.json",
        poll_seconds=60,
        timeout_seconds=20,
        max_attachment_bytes=20 * 1024 * 1024,
        preview_characters=2200,
        mark_existing_on_first_run=True,
    )
    return NaverMailOrganizer(config, naver, server.factory)


class MailOrganizerTests(unittest.TestCase):
    def test_lists_unread_from_all_incoming_folders_without_marking_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            entries, total = service.list_unread()
        self.assertEqual(total, 3)
        self.assertEqual([entry.subject for entry in entries], ["Folder unread", "Newest unread", "Older unread"])
        self.assertNotIn("Sent mail", [entry.subject for entry in entries])
        self.assertTrue(server.readonly_values)
        self.assertTrue(all(server.readonly_values))
        self.assertTrue(all("HEADER.FIELDS" in value for value in server.fetch_specs))

    def test_digest_stores_references_not_bodies_and_mark_read_targets_source_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            digest = service.create_digest()
            selected_id, selected = next(
                (item_id, item)
                for item_id, item in digest["items"].items()
                if item["mailboxName"] == "청구·결제"
            )
            service.mark_read(str(digest["id"]), selected_id)
            state = service.load_state()
        self.assertNotIn("preview", selected)
        self.assertNotIn("body", selected)
        custom = encode_modified_utf7("청구·결제")
        self.assertEqual(server.mailboxes[custom]["seen"], {1})
        self.assertNotIn(selected_id, state["digests"][digest["id"]]["items"])

    def test_open_fetches_body_with_peek_and_import_removal_does_not_mark_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            digest = service.create_digest()
            item_id = next(iter(digest["items"]))
            mail = service.fetch_item(str(digest["id"]), item_id)
            service.remove_imported(str(digest["id"]), item_id)
        self.assertTrue(mail.preview)
        self.assertEqual(server.mailboxes["INBOX"]["seen"], set())
        self.assertIn("(BODY.PEEK[])", server.fetch_specs)

    def test_fetch_message_reads_selected_incoming_folder_without_marking_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            mail = service.fetch_message(mailbox_name="INBOX", uid=7)

        self.assertEqual(mail.subject, "Newest unread")
        self.assertEqual(mail.preview, "Newest body")
        self.assertEqual(server.mailboxes["INBOX"]["seen"], set())
        self.assertIn("(BODY.PEEK[])", server.fetch_specs)
        self.assertTrue(server.readonly_values[-1])

    def test_fetch_message_rejects_excluded_or_unknown_mailbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            with self.assertRaisesRegex(Exception, "mail_message_not_found"):
                service.fetch_message(mailbox_name="Deleted Messages", uid=1)
            with self.assertRaisesRegex(Exception, "mail_message_not_found"):
                service.fetch_message(mailbox_name="Missing", uid=1)

    def test_apply_unread_actions_marks_read_or_moves_to_trash_by_source_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            result = service.apply_unread_actions(
                [
                    {"mailbox": "INBOX", "uid": 7, "uidValidity": "80", "action": "read"},
                    {"mailbox": "청구·결제", "uid": 1, "uidValidity": "84", "action": "delete"},
                ]
            )

        custom = encode_modified_utf7("청구·결제")
        self.assertEqual(result["applied"], {"read": 1, "delete": 1})
        self.assertEqual(server.mailboxes["INBOX"]["seen"], {7})
        self.assertEqual(server.mailboxes[custom]["seen"], set())
        self.assertEqual(server.store_specs, [("7", "+FLAGS.SILENT", "(\\Seen)")])
        self.assertEqual(server.moved, [([1], '"Deleted Messages"')])
        self.assertIn(False, server.readonly_values)

    def test_apply_unread_actions_rejects_stale_uidvalidity_and_duplicate_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            with self.assertRaisesRegex(Exception, "mailbox_generation_changed"):
                service.apply_unread_actions([{"mailbox": "INBOX", "uid": 7, "uidValidity": "stale", "action": "read"}])
            with self.assertRaisesRegex(Exception, "mail_batch_conflict"):
                service.apply_unread_actions(
                    [
                        {"mailbox": "INBOX", "uid": 7, "uidValidity": "80", "action": "read"},
                        {"mailbox": "INBOX", "uid": 7, "uidValidity": "80", "action": "delete"},
                    ]
                )

    def test_import_progress_is_checkpointed_without_storing_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            digest = service.create_digest()
            item_id = next(iter(digest["items"]))
            service.mark_import_summary(str(digest["id"]), item_id, 900)
            service.mark_import_attachment(str(digest["id"]), item_id, "0:notice.pdf:10")
            progress = service.import_progress(str(digest["id"]), item_id)
            state_text = service.config.state_path.read_text()
        self.assertEqual(progress["summaryMessageId"], 900)
        self.assertEqual(progress["uploadedAttachments"], ["0:notice.pdf:10"])
        self.assertNotIn("Newest body", state_text)

    def test_discord_item_message_id_is_checkpointed_for_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            digest = service.create_digest()
            item_id = next(iter(digest["items"]))
            service.attach_message(str(digest["id"]), 300, 400)
            service.attach_item_message(str(digest["id"]), item_id, 500)
            restored = service.active_digests()[0]
        self.assertEqual(restored["channelId"], 300)
        self.assertEqual(restored["messageId"], 400)
        self.assertEqual(restored["items"][item_id]["organizerMessageId"], 500)

    def test_recent_items_returns_digest_references_without_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            digest = service.create_digest()
            service.attach_message(str(digest["id"]), 300, 400)
            rows = service.recent_items()
            state_text = service.config.state_path.read_text(encoding="utf-8")

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["kind"], "mail")
        self.assertEqual(rows[0]["direction"], "incoming")
        self.assertIn("digestId", rows[0])
        self.assertIn("itemId", rows[0])
        self.assertNotIn("body", rows[0])
        self.assertNotIn("Newest body", state_text)

    def test_delete_all_uses_only_digest_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            digest = service.create_digest()
            server.mailboxes["INBOX"]["messages"][9] = server.message(
                "Arrived later", "later@example.test", "Later", "10:00:00"
            )
            service.delete_all(str(digest["id"]))
        moved = {uid for values, _trash in server.moved for uid in values}
        self.assertEqual(moved, {1, 3, 7})
        self.assertNotIn(9, moved)
        self.assertTrue(all(trash == '"Deleted Messages"' for _values, trash in server.moved))

    def test_schedule_sends_due_slot_once_and_validates_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = FakeOrganizerServer()
            service = organizer(Path(tmp), server)
            now = datetime(2026, 8, 12, 10, 0, tzinfo=KST)
            first = service.due_digest(now)
            service.mark_due_sent(now)
            second = service.due_digest(now)
            updated = service.update_schedule(2, "09:05", "17:10")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(updated["runsPerDay"], 2)
        with self.assertRaisesRegex(ValueError, "times_out_of_order"):
            service.update_schedule(2, "18:00", "17:00")


if __name__ == "__main__":
    unittest.main()
