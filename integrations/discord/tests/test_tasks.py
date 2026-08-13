from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.tasks import (
    DiscordTasksSurface,
    TaskView,
    active_tasks,
    render_task_message,
    task_payload,
)


TASKS = [
    {
        "uid": "TASK-1",
        "collection": "zin:tasks",
        "summary": "Buy milk",
        "description": "2L",
        "due": "2026-08-13",
        "dueTime": "09:00",
        "priority": "5",
        "status": "NEEDS-ACTION",
    },
    {
        "uid": "TASK-2",
        "collection": "family:tasks",
        "summary": "Done already",
        "due": "2026-08-12",
        "status": "COMPLETED",
    },
]


class FakeAdapter:
    def __init__(self, tasks=None):
        self.tasks = list(tasks or TASKS)
        self.updated = []
        self.deleted = []

    def list_tasks(self, profile):
        self.profile = profile
        return list(self.tasks)

    def update_task(self, profile, payload):
        self.updated.append((profile, payload))
        self.tasks = [
            {**item, "status": payload["status"]} if item["uid"] == payload["uid"] else item
            for item in self.tasks
        ]
        return {"ok": True, "uid": payload["uid"], "collection": payload["collectionId"]}

    def delete_task(self, profile, uid, collection_id):
        self.deleted.append((profile, uid, collection_id))
        self.tasks = [item for item in self.tasks if item["uid"] != uid]
        return {"ok": True, "uid": uid, "collection": collection_id}


class FakeMessage:
    def __init__(self, message_id):
        self.id = message_id
        self.edits = []
        self.deleted = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        return self

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.messages = {}
        self.next_id = 700

    async def send(self, **kwargs):
        message = FakeMessage(self.next_id)
        self.next_id += 1
        self.sent.append(kwargs)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


class FakeBot:
    def __init__(self, channel):
        self.channel = channel
        self.user = SimpleNamespace(id=900)

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        return self.channel


class DiscordTasksTests(unittest.IsolatedAsyncioTestCase):
    def make_surface(
        self,
        path: Path,
        channel: FakeChannel | None = None,
        adapter: FakeAdapter | None = None,
    ) -> DiscordTasksSurface:
        channel = channel or FakeChannel()
        return DiscordTasksSurface(
            FakeBot(channel),  # type: ignore[arg-type]
            AccessPolicy(100, frozenset({200}), frozenset({300})),
            channel_id=300,
            profile="main",
            state_path=path,
            adapter=adapter or FakeAdapter(),  # type: ignore[arg-type]
        )

    def test_active_tasks_skip_completed_and_render_due_dates(self) -> None:
        active = active_tasks(TASKS)
        content = render_task_message(active[0])

        self.assertEqual([item["uid"] for item in active], ["TASK-1"])
        self.assertIn("### Buy milk", content)
        self.assertIn("- due: 2026-08-13", content)
        self.assertIn("Buy milk", content)
        self.assertIn("2026-08-13", content)
        self.assertNotIn("Done already", content)

    def test_active_tasks_can_filter_to_supplies_collection(self) -> None:
        active = active_tasks(
            [
                {**TASKS[0], "collection": "zin:tasks"},
                {**TASKS[0], "uid": "SUPPLY-1", "collection": "zin:supplies", "summary": "Paper towels"},
            ],
            collection_id="zin:supplies",
        )

        self.assertEqual([item["uid"] for item in active], ["SUPPLY-1"])

    def test_task_payload_preserves_required_update_fields(self) -> None:
        payload = task_payload(TASKS[0], status="COMPLETED")

        self.assertEqual(payload["uid"], "TASK-1")
        self.assertEqual(payload["collectionId"], "zin:tasks")
        self.assertEqual(payload["title"], "Buy milk")
        self.assertEqual(payload["memo"], "2L")
        self.assertEqual(payload["status"], "COMPLETED")

    async def test_ensure_message_creates_one_persistent_message_per_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            tasks = [{**TASKS[0], "uid": "TASK-1"}, {**TASKS[0], "uid": "TASK-3", "summary": "Call school"}]
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, FakeAdapter(tasks=tasks))

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 2)
            self.assertIn("### Buy milk", channel.sent[0]["content"])
            self.assertIn("### Call school", channel.sent[1]["content"])
            self.assertIsInstance(channel.sent[0]["view"], TaskView)
            buttons = channel.sent[0]["view"].children
            self.assertEqual([button.label for button in buttons], ["Done", "Edit", "Delete"])
            self.assertEqual([button.custom_id for button in buttons], ["tasks:done", "tasks:edit", "tasks:delete"])
            self.assertTrue(buttons[1].disabled)
            self.assertEqual(len(surface.state.message_ids), 2)

    async def test_supplies_surface_uses_own_button_prefix_and_collection_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            tasks = [
                {**TASKS[0], "collection": "zin:tasks"},
                {**TASKS[0], "uid": "SUPPLY-1", "collection": "zin:supplies", "summary": "Paper towels"},
            ]
            surface = DiscordTasksSurface(
                FakeBot(channel),  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=Path(temporary) / "supplies.json",
                adapter=FakeAdapter(tasks=tasks),  # type: ignore[arg-type]
                surface_name="supplies",
                button_prefix="supplies",
                collection_id="zin:supplies",
            )

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 1)
            self.assertIn("### Paper towels", channel.sent[0]["content"])
            buttons = channel.sent[0]["view"].children
            self.assertEqual([button.custom_id for button in buttons], ["supplies:done", "supplies:edit", "supplies:delete"])
            self.assertEqual(surface.status()["collectionId"], "zin:supplies")

    async def test_ensure_message_deletes_legacy_combined_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            legacy = FakeMessage(999)
            channel.messages[999] = legacy
            state_path = Path(temporary) / "tasks.json"
            state_path.write_text('{"messageId": 999}', encoding="utf-8")
            surface = self.make_surface(state_path, channel)

            await surface.ensure_message()

            self.assertTrue(legacy.deleted)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotIn("messageId", state)
            self.assertIn("messageIds", state)

    async def test_complete_and_delete_task_buttons_use_adapter_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = FakeAdapter()
            surface = self.make_surface(Path(temporary) / "tasks.json", adapter=adapter)

            await surface.ensure_message()
            self.assertTrue(await surface.complete_task("zin:tasks|TASK-1"))
            self.assertEqual(adapter.updated[0][1]["status"], "COMPLETED")
            self.assertEqual(surface.state.message_ids, {})

            adapter.tasks = [{**TASKS[0], "status": "NEEDS-ACTION"}]
            await surface.ensure_message()
            self.assertTrue(await surface.delete_task("zin:tasks|TASK-1"))
            self.assertEqual(adapter.deleted[0], ("main", "TASK-1", "zin:tasks"))
            self.assertEqual(surface.state.message_ids, {})

    async def test_user_messages_in_tasks_channel_are_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            surface = self.make_surface(Path(temporary) / "tasks.json")
            message = SimpleNamespace(
                id=1,
                content="hello",
                channel=SimpleNamespace(id=300),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            handled = await surface.handle_message(message)  # type: ignore[arg-type]

            self.assertTrue(handled)
            message.delete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
