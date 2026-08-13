from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.tasks import (
    DiscordTasksState,
    DiscordTasksSurface,
    TasksView,
    active_tasks,
    render_active_tasks,
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
        content = render_active_tasks(active)

        self.assertEqual([item["uid"] for item in active], ["TASK-1"])
        self.assertIn("Buy milk", content)
        self.assertIn("2026-08-13", content)
        self.assertNotIn("Done already", content)

    def test_task_payload_preserves_required_update_fields(self) -> None:
        payload = task_payload(TASKS[0], status="COMPLETED")

        self.assertEqual(payload["uid"], "TASK-1")
        self.assertEqual(payload["collectionId"], "zin:tasks")
        self.assertEqual(payload["title"], "Buy milk")
        self.assertEqual(payload["memo"], "2L")
        self.assertEqual(payload["status"], "COMPLETED")

    async def test_ensure_message_creates_persistent_task_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            surface = self.make_surface(Path(temporary) / "tasks.json", channel)

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 1)
            self.assertIn("Active Tasks", channel.sent[0]["content"])
            self.assertIsInstance(channel.sent[0]["view"], TasksView)

    async def test_complete_and_delete_selected_tasks_use_adapter_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = FakeAdapter()
            surface = self.make_surface(Path(temporary) / "tasks.json", adapter=adapter)

            await surface.ensure_message()
            await surface.select_task("zin:tasks|TASK-1")
            self.assertTrue(await surface.complete_selected())
            self.assertEqual(adapter.updated[0][1]["status"], "COMPLETED")

            adapter.tasks = [{**TASKS[0], "status": "NEEDS-ACTION"}]
            await surface.ensure_message()
            await surface.select_task("zin:tasks|TASK-1")
            self.assertTrue(await surface.delete_selected())
            self.assertEqual(adapter.deleted[0], ("main", "TASK-1", "zin:tasks"))

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
