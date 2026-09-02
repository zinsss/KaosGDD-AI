from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from kaos_governor import api


class FakeResponse:
    status = 200

    def __init__(self, body: bytes = b'{"ok": true}') -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeSuppliesCalendar:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, object]]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []
        self.deleted: list[tuple[str, dict[str, object]]] = []
        self.tasks = [
            {
                "uid": "SUPPLY-A",
                "collection": "supplies:list",
                "summary": "gauze",
                "description": "box",
                "status": "NEEDS-ACTION",
                "created": "2026-09-01T09:00:00",
                "lastModified": "2026-09-01T10:00:00",
            },
            {
                "uid": "SUPPLY-B",
                "collection": "supplies:list",
                "summary": "tape",
                "status": "COMPLETED",
                "completed": "2026-09-02T11:00:00",
            },
        ]

    def list_tasks(self, profile: str) -> list[dict[str, object]]:
        if profile != "supplies":
            raise AssertionError(profile)
        return list(self.tasks)

    def vtodo_collection_id(self, profile: str, preferred: str = "") -> str:
        if profile != "supplies":
            raise AssertionError(profile)
        return preferred or "supplies:list"

    def create_task(self, profile: str, payload: dict[str, object]) -> dict[str, object]:
        self.created.append((profile, payload))
        return {"ok": True, "uid": "SUPPLY-C", "collection": payload["collectionId"]}

    def update_task(self, profile: str, payload: dict[str, object]) -> dict[str, object]:
        self.updated.append((profile, payload))
        return {"ok": True, "uid": payload["uid"], "collection": payload["collectionId"]}

    def delete_task(self, profile: str, payload: dict[str, object]) -> dict[str, object]:
        self.deleted.append((profile, payload))
        return {"ok": True, "uid": payload["uid"], "collection": payload["collectionId"]}


class SuppliesApiTests(unittest.TestCase):
    def test_local_calendar_client_maps_supplies_to_supplies_host(self) -> None:
        urlopen = Mock(return_value=FakeResponse())
        with patch.object(api.urllib.request, "urlopen", urlopen):
            api.CalendarAdapterClient("http://calendar-adapter:8091").request_json("supplies", "GET", "/api/calendar/bootstrap")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Host"), "supplies.kaosgdd.net")

    def test_supplies_payload_filters_active_and_done_items(self) -> None:
        client = FakeSuppliesCalendar()

        active = api.supplies_payload("mode=active", client)
        done = api.supplies_payload("mode=done", client)

        self.assertEqual([item["title"] for item in active["items"]], ["gauze"])
        self.assertEqual([item["title"] for item in done["items"]], ["tape"])
        self.assertEqual(active["items"][0]["collectionId"], "supplies:list")

    def test_create_supply_uses_supplies_profile_and_strips_schedule(self) -> None:
        client = FakeSuppliesCalendar()

        result = api.create_supply_payload({"title": "  gauze   refill  ", "dueDate": "2026-09-09"}, client)

        self.assertTrue(result["ok"])
        self.assertEqual(client.created[0][0], "supplies")
        self.assertEqual(
            client.created[0][1],
            {
                "collectionId": "supplies:list",
                "title": "gauze refill",
                "memo": "",
                "dueDate": "",
                "dueTime": "",
                "priority": "",
                "status": "NEEDS-ACTION",
            },
        )

    def test_set_supply_state_uses_existing_collection_and_no_due(self) -> None:
        client = FakeSuppliesCalendar()

        result = api.set_supply_state_payload("SUPPLY-A", "done", client)

        self.assertTrue(result["ok"])
        self.assertEqual(client.updated[0][0], "supplies")
        self.assertEqual(client.updated[0][1]["uid"], "SUPPLY-A")
        self.assertEqual(client.updated[0][1]["collectionId"], "supplies:list")
        self.assertEqual(client.updated[0][1]["status"], "COMPLETED")
        self.assertEqual(client.updated[0][1]["dueDate"], "")

    def test_delete_supply_uses_existing_collection(self) -> None:
        client = FakeSuppliesCalendar()

        result = api.delete_supply_payload("SUPPLY-A", client)

        self.assertTrue(result["deleted"])
        self.assertEqual(client.deleted, [("supplies", {"uid": "SUPPLY-A", "collectionId": "supplies:list"})])

    def test_invalid_supply_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "supply_mode_invalid"):
            api.supplies_payload("mode=lost", FakeSuppliesCalendar())


if __name__ == "__main__":
    unittest.main()
