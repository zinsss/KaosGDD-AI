import importlib.util
import pathlib
import unittest
from unittest import mock


SERVER_PATH = pathlib.Path(__file__).resolve().parents[1] / "apps" / "calendar-adapter" / "server.py"
SPEC = importlib.util.spec_from_file_location("calendar_adapter_gratitude_server", SERVER_PATH)
calendar_adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(calendar_adapter)


def account(key="zin"):
    return {
        "key": key,
        "username": f"{key}-user",
        "password": "secret",
        "label": key,
        "configured": True,
    }


def collection(owner="zin", components=None):
    return {
        "id": f"{owner}:kaos-gratitude",
        "rawId": "kaos-gratitude",
        "name": "감사",
        "owner": owner,
        "ownerLabel": owner,
        "href": f"/{owner}-user/kaos-gratitude/",
        "components": components or ["VJOURNAL"],
    }


class CalendarAdapterGratitudeTests(unittest.TestCase):
    def test_builds_one_plain_text_vjournal_for_five_slots(self):
        owner = account()
        items = ["햇빛", "가족", "따뜻한 밥", "", "산책"]

        uid, body = calendar_adapter.build_gratitude_vjournal(owner, "2026-09-15", items)
        parsed = calendar_adapter.parse_ics(body, "/entry.ics", '"etag-1"')[0]

        self.assertEqual(uid, "KAOS-GRATITUDE-ZIN-20260915")
        self.assertEqual(parsed["component"], "VJOURNAL")
        self.assertEqual(parsed["DTSTART"], "20260915")
        self.assertEqual(parsed["DESCRIPTION"], "\n".join(items))
        self.assertEqual(parsed["CATEGORIES"], "KAOS-GRATITUDE")

    def test_normalizes_and_pads_items(self):
        self.assertEqual(
            calendar_adapter.validate_gratitude_items(["  one  ", "two\nlines"]),
            ["one", "two lines", "", "", ""],
        )
        with self.assertRaisesRegex(ValueError, "gratitude_item_required"):
            calendar_adapter.validate_gratitude_items(["", "  "])

    def test_main_and_family_use_separate_accounts(self):
        zin = account("zin")
        family = account("family")
        accounts = {**calendar_adapter.ACCOUNTS, "zin": zin, "family": family}
        with mock.patch.dict(calendar_adapter.ACCOUNTS, accounts, clear=True), mock.patch.object(
            calendar_adapter, "find_gratitude_collection", return_value=None
        ):
            main_payload = calendar_adapter.list_gratitude("main", "2026-09-15")
            family_payload = calendar_adapter.list_gratitude("family", "2026-09-15")

        self.assertEqual(main_payload["owner"], "zin")
        self.assertEqual(family_payload["owner"], "family")
        self.assertEqual(main_payload["items"], ["", "", "", "", ""])

    def test_rejects_stale_etag_without_writing(self):
        owner = account()
        journal_collection = collection()
        existing = {
            "component": "VJOURNAL",
            "UID": "KAOS-GRATITUDE-ZIN-20260915",
            "DTSTART": "20260915",
            "DESCRIPTION": "old",
            "etag": '"current"',
            "href": "/zin-user/kaos-gratitude/entry.ics",
            "_raw_properties": [],
            "_subcomponents": [],
        }
        with mock.patch.object(calendar_adapter, "gratitude_account", return_value=owner), mock.patch.object(
            calendar_adapter, "ensure_gratitude_collection", return_value=journal_collection
        ), mock.patch.object(calendar_adapter, "find_gratitude_entry", return_value=existing), mock.patch.object(
            calendar_adapter, "radicale_request"
        ) as request:
            with self.assertRaises(calendar_adapter.GratitudeConflict):
                calendar_adapter.put_gratitude(
                    {"date": "2026-09-15", "items": ["new"], "etag": '"stale"'},
                    "main",
                )

        request.assert_not_called()

    def test_creates_new_entry_with_if_none_match(self):
        owner = account()
        journal_collection = collection()
        saved = {
            "component": "VJOURNAL",
            "UID": "KAOS-GRATITUDE-ZIN-20260915",
            "DTSTART": "20260915",
            "DESCRIPTION": "one\\ntwo\\n\\n\\n",
            "LAST-MODIFIED": "20260915T120000Z",
            "etag": '"saved"',
            "href": "/zin-user/kaos-gratitude/KAOS-GRATITUDE-ZIN-20260915.ics",
            "_raw_properties": [],
            "_subcomponents": [],
        }
        with mock.patch.object(calendar_adapter, "gratitude_account", return_value=owner), mock.patch.object(
            calendar_adapter, "ensure_gratitude_collection", return_value=journal_collection
        ), mock.patch.object(calendar_adapter, "find_gratitude_entry", side_effect=[None, saved]), mock.patch.object(
            calendar_adapter, "radicale_request", return_value=(201, "")
        ) as request:
            result = calendar_adapter.put_gratitude(
                {"date": "2026-09-15", "items": ["one", "two"], "etag": ""},
                "main",
            )

        _, method, href, body, headers = request.call_args.args
        self.assertEqual(method, "PUT")
        self.assertTrue(href.endswith("KAOS-GRATITUDE-ZIN-20260915.ics"))
        self.assertIn("BEGIN:VJOURNAL", body)
        self.assertEqual(headers["If-None-Match"], "*")
        self.assertEqual(result["etag"], '"saved"')

    def test_calendar_bootstrap_hides_journal_only_collection(self):
        owner = account()
        journal = collection()
        calendar = {**collection(), "rawId": "calendar", "id": "zin:calendar", "components": ["VEVENT", "VTODO"]}
        with mock.patch.object(calendar_adapter, "profile_accounts", return_value=[owner]), mock.patch.object(
            calendar_adapter, "propfind_collections", return_value=[journal, calendar]
        ), mock.patch.object(calendar_adapter, "report_collection", return_value=[]) as report:
            payload = calendar_adapter.bootstrap_payload("main")

        self.assertEqual([item["id"] for item in payload["collections"]], ["zin:calendar"])
        report.assert_called_once_with(owner, calendar["href"])


if __name__ == "__main__":
    unittest.main()
