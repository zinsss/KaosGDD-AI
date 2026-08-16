from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import AsyncMock

from kaos_governor_discord.access import AccessPolicy
from kaos_governor_discord.tasks import (
    AddTaskCommand,
    CompletedTasksView,
    DiscordTasksSurface,
    RecentSuppliesView,
    TaskEditModal,
    TaskView,
    active_tasks,
    completed_tasks_for_month,
    parse_add_task_message,
    parse_due_line,
    render_completed_archive_message,
    render_recent_supplies_message,
    render_task_message,
    task_payload,
    validate_edit_due,
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
        "completed": "2026-08-15",
        "status": "COMPLETED",
    },
]


class FakeAdapter:
    def __init__(self, tasks=None):
        self.tasks = list(TASKS if tasks is None else tasks)
        self.created = []
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

    def create_task(self, profile, payload):
        uid = f"TASK-{len(self.tasks) + 1}"
        collection = payload.get("collectionId") or "zin:tasks"
        self.created.append((profile, dict(payload)))
        self.tasks.append(
            {
                "uid": uid,
                "collection": collection,
                "summary": payload["title"],
                "description": payload.get("memo") or "",
                "due": payload.get("dueDate") or "",
                "dueTime": payload.get("dueTime") or "",
                "priority": payload.get("priority") or "",
                "status": "NEEDS-ACTION",
            }
        )
        return {"ok": True, "uid": uid, "collection": collection}

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
        completed = render_task_message({**TASKS[0], "status": "COMPLETED"})

        self.assertEqual([item["uid"] for item in active], ["TASK-1"])
        self.assertIn("## Buy milk", content)
        self.assertIn("- due: 2026-08-13 09:00", content)
        self.assertIn("## ~~Buy milk~~", completed)
        self.assertIn("- due: ~~2026-08-13 09:00~~", completed)
        self.assertIn("Buy milk", content)
        self.assertIn("2026-08-13", content)
        self.assertNotIn("Done already", content)

    def test_task_message_omits_due_line_when_due_date_is_missing(self) -> None:
        content = render_task_message({**TASKS[0], "due": ""})
        completed = render_task_message({**TASKS[0], "due": "", "status": "COMPLETED"})

        self.assertEqual(content, "## Buy milk")
        self.assertEqual(completed, "## ~~Buy milk~~")
        self.assertNotIn("No due date", content)

    def test_completed_archive_renders_current_month_history(self) -> None:
        content = render_completed_archive_message(TASKS, month=date(2026, 8, 15))

        self.assertIn("## Completed · 2026.08", content)
        self.assertIn("- 2026.08.15 Done already", content)

    def test_completed_archive_filters_collection(self) -> None:
        completed = completed_tasks_for_month(
            [
                {**TASKS[1], "collection": "family:tasks"},
                {**TASKS[1], "uid": "SUPPLY-1", "collection": "zin:supplies", "summary": "Soap"},
            ],
            collection_id="zin:supplies",
            month=date(2026, 8, 15),
        )

        self.assertEqual([item["summary"] for item in completed], ["Soap"])

    def test_completed_archive_limits_restore_dropdown_to_25_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            tasks = [
                {
                    **TASKS[1],
                    "uid": f"DONE-{index:02d}",
                    "summary": f"Done {index:02d}",
                    "completed": f"2026-08-{(index % 28) + 1:02d}",
                }
                for index in range(30)
            ]
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, FakeAdapter(tasks=tasks))

            view = CompletedTasksView(surface, completed_tasks_for_month(tasks, month=date(2026, 8, 15)))
            select = view.children[0]

            self.assertEqual(len(select.options), 25)
            self.assertEqual(select.custom_id, "tasks:completed:recreate")

    def test_parse_add_task_message_accepts_plus_title_only(self) -> None:
        self.assertEqual(parse_add_task_message("+ Call mom"), AddTaskCommand(title="Call mom"))
        self.assertEqual(parse_add_task_message("  +   엄마한테 전화  "), AddTaskCommand(title="엄마한테 전화"))
        self.assertIsNone(parse_add_task_message("+"))
        self.assertIsNone(parse_add_task_message("Call mom"))

    def test_parse_add_task_message_accepts_strict_due_line(self) -> None:
        self.assertEqual(
            parse_add_task_message("+ Call mom\n:2026-08-15"),
            AddTaskCommand(title="Call mom", due_date="2026-08-15", due_time="10:00"),
        )
        self.assertEqual(
            parse_add_task_message("+ Call mom\n:2026-08-15 14:30"),
            AddTaskCommand(title="Call mom", due_date="2026-08-15", due_time="14:30"),
        )

    def test_parse_add_task_message_rejects_time_only_or_invalid_due_line(self) -> None:
        self.assertIsNone(parse_add_task_message("+ Call mom\n:14:30"))
        self.assertIsNone(parse_add_task_message("+ Call mom\n:2026-08-15 24:00"))
        self.assertIsNone(parse_add_task_message("+ Call mom\n:2026-02-30 10:00"))
        self.assertIsNone(parse_add_task_message("+ Call mom\n2026-08-15 10:00"))
        self.assertIsNone(parse_add_task_message("+ Call mom\n:2026-08-15 10:00\nextra"))

    def test_parse_due_line_defaults_time_and_validates_24_hour_time(self) -> None:
        self.assertEqual(parse_due_line(":2026-08-15"), ("2026-08-15", "10:00"))
        self.assertEqual(parse_due_line(":2026-08-15 00:00"), ("2026-08-15", "00:00"))
        self.assertEqual(parse_due_line(":2026-08-15 23:59"), ("2026-08-15", "23:59"))
        self.assertIsNone(parse_due_line(":2026-08-15 24:00"))
        self.assertIsNone(parse_due_line(":10:00"))

    def test_validate_edit_due_accepts_blank_or_date_and_rejects_time_only(self) -> None:
        self.assertEqual(validate_edit_due("", ""), ("", ""))
        self.assertEqual(validate_edit_due("2026-08-15", ""), ("2026-08-15", "10:00"))
        self.assertEqual(validate_edit_due("2026-08-15", "14:30"), ("2026-08-15", "14:30"))
        self.assertIsNone(validate_edit_due("", "14:30"))
        self.assertIsNone(validate_edit_due("2026-02-30", "10:00"))

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

            self.assertEqual(len(channel.sent), 3)
            self.assertIn("## Completed", channel.sent[0]["content"])
            self.assertIn("## Buy milk", channel.sent[1]["content"])
            self.assertIn("## Call school", channel.sent[2]["content"])
            self.assertIsNone(channel.sent[0]["view"])
            self.assertIsInstance(channel.sent[1]["view"], TaskView)
            buttons = channel.sent[1]["view"].children
            self.assertEqual([button.label for button in buttons], ["Done", "Edit", "Delete"])
            self.assertEqual([button.custom_id for button in buttons], ["tasks:done", "tasks:edit", "tasks:delete"])
            self.assertFalse(buttons[1].disabled)
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
                show_due=False,
            )

            await surface.ensure_message()

            self.assertEqual(len(channel.sent), 3)
            self.assertIn("## Completed", channel.sent[0]["content"])
            self.assertIsNone(channel.sent[0]["view"])
            self.assertIn("## Paper towels", channel.sent[1]["content"])
            self.assertIn("## 최근 준비물", channel.sent[2]["content"])
            self.assertNotIn("- due:", channel.sent[1]["content"])
            buttons = channel.sent[1]["view"].children
            self.assertEqual([button.custom_id for button in buttons], ["supplies:done", "supplies:edit", "supplies:delete"])
            self.assertEqual(surface.status()["collectionId"], "zin:supplies")

    async def test_plus_message_creates_task_without_due_date_and_deletes_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(tasks=[])
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)
            message = SimpleNamespace(
                id=1,
                content="+ Call mom",
                channel=SimpleNamespace(id=300),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            handled = await surface.handle_message(message)  # type: ignore[arg-type]

            self.assertTrue(handled)
            message.delete.assert_awaited_once()
            self.assertEqual(adapter.created[0][0], "main")
            self.assertEqual(adapter.created[0][1]["title"], "Call mom")
            self.assertEqual(adapter.created[0][1]["dueDate"], "")
            self.assertNotIn("collectionId", adapter.created[0][1])
            self.assertEqual(len(channel.sent), 2)
            self.assertIn("## Completed", channel.sent[0]["content"])
            self.assertIn("- none", channel.sent[0]["content"])
            self.assertIsNone(channel.sent[0]["view"])
            self.assertEqual(channel.sent[1]["content"], "## Call mom")

    async def test_plus_message_creates_task_with_strict_due_date_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(tasks=[])
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)
            message = SimpleNamespace(
                id=1,
                content="+ Call mom\n:2026-08-15 14:30",
                channel=SimpleNamespace(id=300),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            self.assertTrue(await surface.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(adapter.created[0][1]["title"], "Call mom")
            self.assertEqual(adapter.created[0][1]["dueDate"], "2026-08-15")
            self.assertEqual(adapter.created[0][1]["dueTime"], "14:30")
            self.assertEqual(channel.sent[1]["content"], "## Call mom\n- due: 2026-08-15 14:30")

    async def test_plus_message_defaults_due_time_to_ten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(tasks=[])
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)
            message = SimpleNamespace(
                id=1,
                content="+ Call mom\n:2026-08-15",
                channel=SimpleNamespace(id=300),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            self.assertTrue(await surface.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(adapter.created[0][1]["dueDate"], "2026-08-15")
            self.assertEqual(adapter.created[0][1]["dueTime"], "10:00")

    async def test_invalid_due_line_deletes_command_without_creating_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(tasks=[])
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)
            message = SimpleNamespace(
                id=1,
                content="+ Call mom\n:14:30",
                channel=SimpleNamespace(id=300),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            self.assertTrue(await surface.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(adapter.created, [])
            self.assertEqual(channel.sent, [])
            message.delete.assert_awaited_once()

    async def test_plus_message_for_supplies_uses_supplies_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(tasks=[])
            surface = DiscordTasksSurface(
                FakeBot(channel),  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=Path(temporary) / "supplies.json",
                adapter=adapter,  # type: ignore[arg-type]
                surface_name="supplies",
                button_prefix="supplies",
                collection_id="zin:supplies",
                show_due=False,
            )
            message = SimpleNamespace(
                id=1,
                content="+ Paper towels",
                channel=SimpleNamespace(id=300),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            self.assertTrue(await surface.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(adapter.created[0][1]["collectionId"], "zin:supplies")
            self.assertEqual(adapter.created[0][1]["dueDate"], "")
            self.assertEqual(adapter.created[0][1]["dueTime"], "")
            self.assertEqual(channel.sent[1]["content"], "## Paper towels")
            self.assertEqual(channel.sent[2]["content"], "## 최근 준비물\n- + Paper towels")
            self.assertIsInstance(channel.sent[2]["view"], RecentSuppliesView)
            select = channel.sent[2]["view"].children[0]
            self.assertEqual(select.custom_id, "supplies:recent:add")
            self.assertEqual([option.label for option in select.options], ["Paper towels"])

    async def test_supplies_recent_message_keeps_latest_25_inputs_at_bottom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(tasks=[])
            surface = DiscordTasksSurface(
                FakeBot(channel),  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=Path(temporary) / "supplies.json",
                adapter=adapter,  # type: ignore[arg-type]
                surface_name="supplies",
                button_prefix="supplies",
                collection_id="zin:supplies",
                show_due=False,
            )

            for index in range(27):
                self.assertTrue(await surface.create_task(f"Item {index:02d}"))
            self.assertTrue(await surface.create_task("Item 05"))

            self.assertEqual(surface.state.recent_supplies[0], "Item 05")
            self.assertEqual(len(surface.state.recent_supplies), 25)
            self.assertNotIn("Item 00", surface.state.recent_supplies)
            latest_content = channel.sent[-1]["content"]
            self.assertIn("## 최근 준비물", latest_content)
            self.assertIn("- + Item 05", latest_content.splitlines()[1])
            self.assertIsInstance(channel.sent[-1]["view"], RecentSuppliesView)
            select = channel.sent[-1]["view"].children[0]
            self.assertEqual(len(select.options), 25)
            self.assertEqual(select.options[0].label, "Item 05")
            self.assertEqual(surface.status()["recentSuppliesCount"], 25)

    async def test_supplies_surface_strips_due_dates_as_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(tasks=[])
            surface = DiscordTasksSurface(
                FakeBot(channel),  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=Path(temporary) / "supplies.json",
                adapter=adapter,  # type: ignore[arg-type]
                surface_name="supplies",
                button_prefix="supplies",
                collection_id="zin:supplies",
                show_due=False,
            )
            message = SimpleNamespace(
                id=1,
                content="+ Paper towels\n:2026-08-17 10:00",
                channel=SimpleNamespace(id=300),
                author=SimpleNamespace(id=200, bot=False),
                delete=AsyncMock(),
            )

            self.assertTrue(await surface.handle_message(message))  # type: ignore[arg-type]

            self.assertEqual(adapter.created[0][1]["collectionId"], "zin:supplies")
            self.assertEqual(adapter.created[0][1]["dueDate"], "")
            self.assertEqual(adapter.created[0][1]["dueTime"], "")

    def test_render_recent_supplies_message_escapes_and_limits_items(self) -> None:
        content = render_recent_supplies_message(["@everyone", *[f"Item {index}" for index in range(30)]])

        self.assertIn("- + @\u200beveryone", content)
        self.assertIn("- + Item 23", content)
        self.assertNotIn("- + Item 24", content)

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
            channel = FakeChannel()
            adapter = FakeAdapter()
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)

            await surface.ensure_message()
            self.assertTrue(await surface.complete_task("zin:tasks|TASK-1"))
            self.assertEqual(adapter.updated[0][1]["status"], "COMPLETED")
            self.assertEqual(surface.state.message_ids, {})
            summary_message = channel.messages[700]
            completed_message = channel.messages[701]
            self.assertIn("## Completed", summary_message.edits[-1]["content"])
            self.assertIn("Buy milk", summary_message.edits[-1]["content"])
            self.assertIsInstance(summary_message.edits[-1]["view"], CompletedTasksView)
            self.assertFalse(completed_message.deleted)
            self.assertIn("## ~~Buy milk~~", completed_message.edits[-1]["content"])
            self.assertIsNone(completed_message.edits[-1]["view"])

            adapter.tasks = [{**TASKS[0], "status": "NEEDS-ACTION"}]
            await surface.ensure_message()
            self.assertTrue(await surface.delete_task("zin:tasks|TASK-1"))
            self.assertEqual(adapter.deleted[0], ("main", "TASK-1", "zin:tasks"))
            self.assertEqual(surface.state.message_ids, {})

    async def test_edit_button_opens_prefilled_task_modal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            surface = self.make_surface(Path(temporary) / "tasks.json", channel)
            await surface.ensure_message()
            view = channel.sent[1]["view"]
            edit = view.children[1]
            interaction = SimpleNamespace(
                guild_id=100,
                channel_id=300,
                user=SimpleNamespace(id=200),
                response=SimpleNamespace(send_modal=AsyncMock(), is_done=lambda: False),
                followup=SimpleNamespace(send=AsyncMock()),
            )

            await edit.callback(interaction)  # type: ignore[arg-type]

            modal = interaction.response.send_modal.await_args.args[0]
            self.assertIsInstance(modal, TaskEditModal)
            self.assertEqual(len(modal.children), 5)
            self.assertEqual(str(modal.title_input.default), "Buy milk")
            self.assertEqual(str(modal.memo_input.default), "2L")

    async def test_task_edit_modal_updates_title_memo_due_and_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter()
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)
            await surface.ensure_message()
            modal = TaskEditModal(surface, "zin:tasks|TASK-1", TASKS[0])
            modal.title_input.default = "Buy oat milk"
            modal.memo_input.default = "1L"
            modal.due_date_input.default = "2026-08-20"
            modal.due_time_input.default = "14:30"
            modal.priority_input.default = "1"
            modal.title_input._value = "Buy oat milk"
            modal.memo_input._value = "1L"
            modal.due_date_input._value = "2026-08-20"
            modal.due_time_input._value = "14:30"
            modal.priority_input._value = "1"
            interaction = SimpleNamespace(
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
            )

            await modal.on_submit(interaction)  # type: ignore[arg-type]

            self.assertEqual(adapter.updated[-1][1]["title"], "Buy oat milk")
            self.assertEqual(adapter.updated[-1][1]["memo"], "1L")
            self.assertEqual(adapter.updated[-1][1]["dueDate"], "2026-08-20")
            self.assertEqual(adapter.updated[-1][1]["dueTime"], "14:30")
            self.assertEqual(adapter.updated[-1][1]["priority"], "1")
            interaction.followup.send.assert_not_called()

    async def test_supplies_edit_modal_uses_title_and_memo_only_and_strips_due(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(
                tasks=[
                    {
                        **TASKS[0],
                        "uid": "SUPPLY-1",
                        "collection": "zin:supplies",
                        "summary": "Paper towels",
                        "description": "kitchen",
                        "due": "2026-08-20",
                        "dueTime": "14:30",
                    }
                ]
            )
            surface = DiscordTasksSurface(
                FakeBot(channel),  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=Path(temporary) / "supplies.json",
                adapter=adapter,  # type: ignore[arg-type]
                surface_name="supplies",
                button_prefix="supplies",
                collection_id="zin:supplies",
                show_due=False,
            )
            await surface.ensure_message()
            modal = TaskEditModal(surface, "zin:supplies|SUPPLY-1", adapter.tasks[0])
            self.assertEqual(len(modal.children), 2)
            modal.title_input._value = "Napkins"
            modal.memo_input._value = "table"
            interaction = SimpleNamespace(
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
            )

            await modal.on_submit(interaction)  # type: ignore[arg-type]

            self.assertEqual(adapter.updated[-1][1]["title"], "Napkins")
            self.assertEqual(adapter.updated[-1][1]["memo"], "table")
            self.assertEqual(adapter.updated[-1][1]["dueDate"], "")
            self.assertEqual(adapter.updated[-1][1]["dueTime"], "")
            self.assertEqual(adapter.updated[-1][1]["priority"], "")

    async def test_task_edit_modal_rejects_invalid_due(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter()
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)
            await surface.ensure_message()
            modal = TaskEditModal(surface, "zin:tasks|TASK-1", TASKS[0])
            modal.title_input._value = "Buy milk"
            modal.memo_input._value = ""
            modal.due_date_input._value = ""
            modal.due_time_input._value = "14:30"
            modal.priority_input._value = ""
            interaction = SimpleNamespace(
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
            )

            await modal.on_submit(interaction)  # type: ignore[arg-type]

            self.assertEqual(adapter.updated, [])
            interaction.followup.send.assert_awaited_once()

    async def test_recreate_completed_task_preserves_due_for_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(
                tasks=[
                    {
                        **TASKS[1],
                        "uid": "DONE-1",
                        "collection": "zin:tasks",
                        "summary": "Renew license",
                        "due": "2026-08-20",
                        "dueTime": "14:30",
                    }
                ]
            )
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, adapter)

            await surface.ensure_message()
            view = channel.sent[0]["view"]
            interaction = SimpleNamespace(
                guild_id=100,
                channel_id=300,
                user=SimpleNamespace(id=200),
                response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
                followup=SimpleNamespace(send=AsyncMock()),
            )

            await view._select_callback(SimpleNamespace(values=["0"]))(interaction)  # type: ignore[attr-defined,arg-type]

            self.assertEqual(adapter.created[-1][1]["title"], "Renew license")
            self.assertEqual(adapter.created[-1][1]["dueDate"], "2026-08-20")
            self.assertEqual(adapter.created[-1][1]["dueTime"], "14:30")

    async def test_recreate_completed_supply_strips_due_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            adapter = FakeAdapter(
                tasks=[
                    {
                        **TASKS[1],
                        "uid": "SUPPLY-DONE-1",
                        "collection": "zin:supplies",
                        "summary": "Paper towels",
                        "due": "2026-08-20",
                        "dueTime": "14:30",
                    }
                ]
            )
            surface = DiscordTasksSurface(
                FakeBot(channel),  # type: ignore[arg-type]
                AccessPolicy(100, frozenset({200}), frozenset({300})),
                channel_id=300,
                profile="main",
                state_path=Path(temporary) / "supplies.json",
                adapter=adapter,  # type: ignore[arg-type]
                surface_name="supplies",
                button_prefix="supplies",
                collection_id="zin:supplies",
                show_due=False,
            )

            await surface.ensure_message()
            view = channel.sent[0]["view"]
            self.assertIsInstance(view, CompletedTasksView)
            select = view.children[0]
            self.assertEqual(select.custom_id, "supplies:completed:recreate")
            interaction = SimpleNamespace(
                guild_id=100,
                channel_id=300,
                user=SimpleNamespace(id=200),
                response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
                followup=SimpleNamespace(send=AsyncMock()),
            )

            await view._select_callback(SimpleNamespace(values=["0"]))(interaction)  # type: ignore[attr-defined,arg-type]

            self.assertEqual(adapter.created[-1][1]["title"], "Paper towels")
            self.assertEqual(adapter.created[-1][1]["collectionId"], "zin:supplies")
            self.assertEqual(adapter.created[-1][1]["dueDate"], "")
            self.assertEqual(adapter.created[-1][1]["dueTime"], "")

    async def test_repost_active_messages_moves_active_items_to_channel_bottom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            channel = FakeChannel()
            tasks = [{**TASKS[0], "uid": "TASK-1"}, {**TASKS[0], "uid": "TASK-3", "summary": "Call school"}]
            surface = self.make_surface(Path(temporary) / "tasks.json", channel, FakeAdapter(tasks=tasks))

            await surface.ensure_message()
            first_ids = dict(surface.state.message_ids)

            await surface.repost_active_messages()

            self.assertEqual(len(channel.sent), 5)
            self.assertTrue(channel.messages[first_ids["zin:tasks|TASK-1"]].deleted)
            self.assertTrue(channel.messages[first_ids["zin:tasks|TASK-3"]].deleted)
            self.assertEqual(set(surface.state.message_ids), set(first_ids))
            self.assertNotEqual(surface.state.message_ids, first_ids)
            self.assertIn("## Buy milk", channel.sent[3]["content"])
            self.assertIn("## Call school", channel.sent[4]["content"])

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
