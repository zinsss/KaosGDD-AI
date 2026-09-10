from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from kaos_governor.scribble import ScribbleError, ScribbleStore


class ScribbleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ScribbleStore(Path(self.temporary.name) / "index.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_text_can_be_captured_edited_and_removed(self) -> None:
        created = self.store.create(text="quick thought", source="shortcut")
        self.assertEqual(created.title, "quick thought")
        self.assertEqual(created.as_dict()["kind"], "text")

        updated = self.store.update(created.item_id, title="Later", text="edited")
        self.assertEqual(updated.title, "Later")
        self.assertEqual(self.store.list_items()[0].text, "edited")

        self.store.delete(created.item_id)
        self.assertEqual(self.store.list_items(), [])

    def test_file_is_stored_outside_index_and_deleted_with_item(self) -> None:
        created = self.store.create(
            title="Referral",
            filename="referral.pdf",
            content=b"%PDF-1.4 test",
            content_type="application/pdf",
        )
        index_text = self.store.index_path.read_text(encoding="utf-8")
        self.assertNotIn("%PDF-1.4", index_text)
        item, content = self.store.read_file(created.item_id)
        self.assertEqual(item.filename, "referral.pdf")
        self.assertEqual(content, b"%PDF-1.4 test")

        self.store.delete(created.item_id)
        with self.assertRaisesRegex(ScribbleError, "scribble_not_found"):
            self.store.read_file(created.item_id)

    def test_empty_capture_is_rejected(self) -> None:
        with self.assertRaisesRegex(ScribbleError, "scribble_content_required"):
            self.store.create()

    def test_items_and_files_expire_after_30_days(self) -> None:
        created = self.store.create(filename="old.pdf", content=b"old")
        file_path = self.store.files_root / created.item_id / created.filename
        payload = json.loads(self.store.index_path.read_text(encoding="utf-8"))
        expired_at = datetime.now(UTC) - timedelta(days=31)
        payload["items"][0]["createdAt"] = expired_at.isoformat().replace("+00:00", "Z")
        self.store.index_path.write_text(json.dumps(payload), encoding="utf-8")

        self.assertEqual(self.store.list_items(), [])
        self.assertFalse(file_path.exists())


if __name__ == "__main__":
    unittest.main()
