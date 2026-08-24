from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from kaos_brain.bot import (
    ACTIVE_CONTROL_HISTORY_LIMIT,
    ACTIVE_TASKS_LABEL,
    ACTIVE_TASKS_TITLE,
    BrainActiveControlSelect,
    BrainActiveControlView,
    BrainActiveTaskActionsView,
    BrainActiveTasksSelect,
    BrainActiveTasksView,
    BrainCalendarMonthView,
    BrainDeletedMemoView,
    BrainCompletedTaskActionsView,
    BrainTaskEditModal,
    BrainCompletedTasksSelect,
    BrainCompletedTasksView,
    BrainTaskHistorySelect,
    BrainCombinedSearchFullButton,
    BrainCombinedSearchView,
    BrainDocumentSearchSelect,
    BrainDocumentSearchView,
    BrainFaxMailView,
    BrainMemoDeleteConfirmView,
    BrainMemoEditConfirmView,
    BrainOpenedDocumentView,
    BrainServiceMenuView,
    BrainUpcomingEventsSelect,
    BrainMemoSearchSelect,
    BrainMemoSearchView,
    CALENDAR_LABEL,
    CALENDAR_TITLE,
    FAX_MAIL_LABEL,
    FAX_MAIL_PAGE_SIZE,
    FAX_MAIL_TITLE,
    MEMOS_LABEL,
    MEMOS_TITLE,
    PAPERLESS_LABEL,
    PAPERLESS_TITLE,
    SUPPLIES_LABEL,
    SUPPLIES_TITLE,
    TASKS_SERVICE_BUTTON_LABEL,
    TaskCreateConfirmationView,
    UPCOMING_EVENTS_LABEL,
    _read_active_control_message_id,
    _read_active_control_service_message_id,
    _is_transient_brain_message,
    _write_active_control_message_id,
    render_active_control_message,
)
from kaos_brain.tool_intent import ToolKind, ToolRequest


class FakeGovernorTools:
    def __init__(self) -> None:
        self.task_action_calls = []
        self.task_create_calls = []
        self.task_edit_calls = []
        self.approve_calls = []

    async def get_memo(self, name: str):
        return {"memo": {"name": name, "content": "# Rustdesk\nUse Tailscale."}}

    async def get_document(self, document_id: object):
        return {
            "document": {
                "id": document_id,
                "title": "Insurance receipt",
                "filename": "receipt.pdf",
                "correspondent": "Clinic",
            }
        }

    async def propose_task_action(self, request, *, actor_id: int, idempotency_key: str):
        self.task_action_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-1",
            "task": {
                "title": request.task_title,
                "action": request.action,
                "due": "",
                "dueTime": "",
            },
        }

    async def propose_task_create(self, request, *, actor_id: int, idempotency_key: str):
        self.task_create_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-create-1",
            "task": {
                "title": request.title,
                "memo": request.memo,
                "profile": request.profile,
                "due": request.due_date,
                "dueTime": request.due_time,
            },
        }

    async def propose_task_edit(self, request, *, actor_id: int, idempotency_key: str):
        self.task_edit_calls.append((request, actor_id, idempotency_key))
        return {
            "confirmationId": "confirm-edit-1",
            "task": {
                "oldTitle": request.task_title,
                "title": request.title,
                "oldDue": "",
                "oldDueTime": "",
                "due": request.due_date,
                "dueTime": request.due_time,
            },
        }

    async def approve_confirmation(self, confirmation_id: str, *, actor_id: int):
        self.approve_calls.append((confirmation_id, actor_id))
        return {"task": {"title": "오도리 문고리", "due": "", "dueTime": ""}}

    async def fetch(self, request):
        if request.kind is ToolKind.UPCOMING_EVENTS:
            return {"events": [{"title": "Clinic", "date": "2026-08-22", "time": "10:50", "ownerLabel": "Family"}]}
        if request.kind is ToolKind.RECENT_IMPORTS:
            return {
                "imports": [
                    {"kind": "mail", "title": "Naver organizer digests: 1", "detail": "2026-08-22T09:00:00Z"},
                    {"kind": "fax", "title": "Fax jobs tracked: 1", "detail": "2026-08-22T10:00:00Z"},
                    {"kind": "documents", "title": "Documents accepted: 1", "detail": "OCR ready: 1"},
                ]
            }
        if request.profile == "supplies":
            return {"tasks": [{"title": "토프라민", "date": "2026-08-21", "due": "2026-08-21"}]}
        return {"tasks": [{"title": "로운이 제로이드", "due": "2026-08-22", "dueTime": "10:00"}]}

    async def completed_tasks(self, request, *, limit: int = 25):
        return {
            "tasks": [
                {"uid": f"done-{index}", "title": f"Done {index:02d}", "completedDate": "2026-08-15"}
                for index in range(1, min(limit, 30) + 1)
            ]
        }

    async def calendar_month_image(self, *, profile: str = "", year: int | None = None, month: int | None = None):
        return {"contentType": "text/plain", "contentBase64": "", "filename": "calendar.txt"}

    async def today(self, *, profile: str = "", day: object | None = None):
        return {
            "date": str(day or "2026-08-22"),
            "weather": {"summary": "⛅️ 23-28℃"},
            "events": [{"title": "Clinic", "date": str(day or "2026-08-22"), "time": "10:50", "ownerLabel": "GDD_ZiN"}],
        }

    async def calendar_week(self, *, profile: str = "", start: object | None = None, days: int = 7):
        base = datetime.fromisoformat(str(start or "2026-08-22")).date()
        return {
            "date": base.isoformat(),
            "days": days,
            "items": [
                {
                    "date": (base + timedelta(days=offset)).isoformat(),
                    "weather": {"summary": "⛅️ 23-28℃"},
                    "events": [
                        {"title": "Clinic", "time": "10:50", "ownerLabel": "GDD_ZiN"},
                        {"title": "School", "time": "15:00", "ownerLabel": "Family"},
                    ]
                    if offset in (0, 2)
                    else [],
                }
                for offset in range(days)
            ],
        }

    async def propose_memo_create(self, request, *, actor_id: int, idempotency_key: str):
        return {"confirmationId": "confirm-memo-create", "memo": {"content": request.content}}

    async def propose_memo_delete_by_name(self, name: str, *, actor_id: int, idempotency_key: str):
        return {"confirmationId": "confirm-memo-delete", "memo": {"name": name}}


class BrainBotViewTests(unittest.IsolatedAsyncioTestCase):
    def active_control_settings(self):
        return SimpleNamespace(
            guild_id=100,
            brain_channel_id=300,
            allowed_user_ids=frozenset({200}),
            governor_tools_profile="main",
            governor_tools_supplies_collection_id="supplies:abc",
        )

    def test_active_control_message_uses_compact_date_header(self) -> None:
        content = render_active_control_message(
            [{"title": "Clinic"}],
            [{"title": "Task"}],
            [{"title": "Supply"}],
            now=datetime(2026, 9, 12),
        )

        self.assertEqual(content, "# 2026.09.12(Sat)")
        self.assertEqual(ACTIVE_CONTROL_HISTORY_LIMIT, 20)

    def test_rrr_transient_cleanup_filter_keeps_durable_messages(self) -> None:
        self.assertTrue(_is_transient_brain_message("Confirm New Task\n## 오도리 문고리"))
        self.assertTrue(_is_transient_brain_message("할 일 변경 실패했어요."))
        self.assertTrue(_is_transient_brain_message("Task added."))
        self.assertFalse(_is_transient_brain_message("# 2026.08.24(Mon)"))
        self.assertFalse(_is_transient_brain_message("## Documents\n### 의료폐기물 배출자 교육"))
        self.assertFalse(_is_transient_brain_message("\u200b"))

    def test_active_control_message_id_state_round_trips(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_path = str(Path(tmpdir) / "nested" / "active-control.json")

            self.assertEqual(_read_active_control_message_id(state_path), 0)
            self.assertEqual(_read_active_control_service_message_id(state_path), 0)
            _write_active_control_message_id(state_path, 1536983928337076224, 1536983928337076225)

            self.assertEqual(_read_active_control_message_id(state_path), 1536983928337076224)
            self.assertEqual(_read_active_control_service_message_id(state_path), 1536983928337076225)

    async def test_active_control_select_opens_existing_action_view(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [],
            [{"title": "로운이 제로이드", "due": "2026-08-22", "dueTime": "10:00"}],
            [{"title": "토프라민"}],
            [],
        )
        task_select = next(
            child
            for child in view.children
            if isinstance(child, BrainActiveControlSelect) and child.kind == "tasks"
        )
        task_select._values = ["0"]
        interaction = SimpleNamespace(
            id=700,
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await task_select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn("## 로운이 제로이드", content)
        self.assertIn("- due: 2026-08-22 10:00", content)
        action_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(action_view, BrainActiveTaskActionsView)
        self.assertEqual([item.label for item in action_view.children], ["Complete", "Edit", "Delete", "Close"])

    async def test_active_control_keeps_dropdowns_and_reload_button(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [{"title": "Clinic", "date": "2026-08-22"}],
            [{"title": "로운이 제로이드"}],
            [{"title": "토프라민"}],
            [{"kind": "fax", "title": "Fax jobs tracked: 1"}],
        )

        self.assertEqual(
            [getattr(child, "placeholder", "") for child in view.children if getattr(child, "placeholder", "")],
            [
                f"{UPCOMING_EVENTS_LABEL}: 1",
                f"{ACTIVE_TASKS_LABEL}: 1",
                f"{SUPPLIES_LABEL}: 1",
                f"{FAX_MAIL_LABEL}: 1",
            ],
        )
        self.assertEqual(
            [getattr(child, "label", "") for child in view.children if getattr(child, "label", "")],
            ["Reload"],
        )

    async def test_active_control_dropdown_descriptions_only_show_task_due_dates(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [],
            [
                {"title": "No due task", "date": "2026-08-21"},
                {"title": "Due task", "dueDate": "2026-08-22", "dueTime": "10:00"},
            ],
            [{"title": "실프포어", "date": "2026-08-21", "dueDate": "2026-08-21"}],
            [],
        )
        task_select = next(
            child
            for child in view.children
            if isinstance(child, BrainActiveControlSelect) and child.kind == "tasks"
        )
        supplies_select = next(
            child
            for child in view.children
            if isinstance(child, BrainActiveControlSelect) and child.kind == "supplies"
        )

        self.assertIsNone(task_select.options[0].description)
        self.assertEqual(task_select.options[1].description, "2026-08-22 10:00")
        self.assertIsNone(supplies_select.options[0].description)

    async def test_tasks_button_calls_up_active_tasks_message(self) -> None:
        view = BrainServiceMenuView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
        )
        button = next(child for child in view.children if getattr(child, "label", "") == TASKS_SERVICE_BUTTON_LABEL)
        interaction = SimpleNamespace(
            id=701,
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await button.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn(f"## {ACTIVE_TASKS_TITLE}", content)
        self.assertIn("- active: 1", content)
        self.assertIn("- 로운이 제로이드", content)
        self.assertIsInstance(interaction.followup.send.await_args.kwargs["view"], BrainActiveTasksView)

    async def test_calendar_button_calls_up_closable_month_message(self) -> None:
        view = BrainServiceMenuView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
        )
        button = next(child for child in view.children if getattr(child, "label", "") == CALENDAR_LABEL)
        interaction = SimpleNamespace(
            id=702,
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await button.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        self.assertIn(f"## {CALENDAR_TITLE} ·", interaction.followup.send.await_args.kwargs["content"])
        service_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(service_view, BrainCalendarMonthView)
        self.assertEqual([getattr(item, "label", "") for item in service_view.children], ["Month", "Weekly", "Close", "<", "Today", ">"])

    async def test_calendar_weekly_view_edits_to_weather_event_list(self) -> None:
        view = BrainCalendarMonthView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            anchor_date=datetime(2026, 8, 22).date(),
            year=2026,
            month=8,
        )
        button = next(child for child in view.children if getattr(child, "label", "") == "Weekly")
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await button.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertIn(f"## {CALENDAR_TITLE} · 𝓦𝓮𝓮𝓴𝓵𝔂", kwargs["content"])
        self.assertIn("- 2026.08.16 - 2026.08.22", kwargs["content"])
        self.assertIn("⛅️ 23-28℃", kwargs["content"])
        self.assertIn("### 2026.08.16 Sun", kwargs["content"])
        self.assertIn("### 2026.08.18 Tue", kwargs["content"])
        self.assertNotIn("### 2026.08.17 Mon", kwargs["content"])
        self.assertNotIn("### 2026.08.23 Sun", kwargs["content"])
        self.assertNotIn("일정 없음", kwargs["content"])
        self.assertIn("Clinic  • 𝘎𝘋𝘋𝙕𝘪𝙉", kwargs["content"])
        self.assertIn("School  • 𝘧𝘢𝘮𝘪𝘭𝘺", kwargs["content"])
        self.assertNotIn("GDD_ZiN", kwargs["content"])
        self.assertEqual(kwargs["attachments"], [])

    async def test_paperless_and_memos_buttons_are_separate(self) -> None:
        view = BrainServiceMenuView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
        )
        paperless = next(child for child in view.children if getattr(child, "label", "") == PAPERLESS_LABEL)
        memos = next(child for child in view.children if getattr(child, "label", "") == MEMOS_LABEL)
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        await paperless.callback(interaction)  # type: ignore[arg-type,union-attr]
        await memos.callback(interaction)  # type: ignore[arg-type,union-attr]

        calls = interaction.response.send_message.await_args_list
        self.assertIn(f"## {PAPERLESS_TITLE}", calls[0].args[0])
        self.assertIn(f"## {MEMOS_TITLE}", calls[1].args[0])

    async def test_fax_mail_button_calls_up_incoming_service_message(self) -> None:
        view = BrainServiceMenuView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
        )
        button = next(child for child in view.children if getattr(child, "label", "") == FAX_MAIL_LABEL)
        interaction = SimpleNamespace(
            id=704,
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await button.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn(f"## {FAX_MAIL_TITLE}", content)
        self.assertIn("### Incoming Fax Mail", content)
        self.assertIn("- total: 1", content)
        self.assertNotIn("Naver organizer digests", content)
        self.assertIn("- Fax jobs tracked: 1", content)
        self.assertNotIn("Documents accepted", content)
        service_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(service_view, BrainFaxMailView)
        self.assertIn("Outgoing Fax", [getattr(item, "label", "") for item in service_view.children])
        self.assertIn("Close", [getattr(item, "label", "") for item in service_view.children])

    async def test_fax_mail_outgoing_message_paginates(self) -> None:
        imports = [
            {"kind": "fax", "direction": "outgoing", "title": f"Fax job {index:02d}", "detail": "queued"}
            for index in range(1, FAX_MAIL_PAGE_SIZE + 2)
        ]
        view = BrainFaxMailView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            self.active_control_settings(),
            imports,
            mode="outgoing",
        )

        content = view.content()

        self.assertIn(f"## {FAX_MAIL_TITLE}", content)
        self.assertIn("### Outgoing Fax", content)
        self.assertIn(f"- showing: 1-{FAX_MAIL_PAGE_SIZE}", content)
        self.assertIn("Fax job 01", content)
        self.assertNotIn(f"Fax job {FAX_MAIL_PAGE_SIZE + 1:02d}", content)
        self.assertEqual(
            [getattr(item, "label", "") for item in view.children if getattr(item, "label", "")],
            ["←", "Page 1/2", "→", "Incoming", "Close"],
        )

    async def test_supplies_button_calls_up_named_shopping_list_without_dates(self) -> None:
        view = BrainServiceMenuView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
        )
        button = next(child for child in view.children if getattr(child, "label", "") == SUPPLIES_LABEL)
        interaction = SimpleNamespace(
            id=703,
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await button.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn(f"## {SUPPLIES_TITLE}", content)
        self.assertIn("- active: 1", content)
        self.assertIn("- 토프라민", content)
        self.assertNotIn("2026-", content)

    async def test_active_control_refresh_rebuilds_dropdowns(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [{"title": "Clinic", "date": "2026-08-22", "time": "10:50", "ownerLabel": "Family"}],
            [],
            [],
            [],
        )
        refresh = next(child for child in view.children if getattr(child, "label", "") == "Reload")
        interaction = SimpleNamespace(
            guild_id=100,
            channel_id=300,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await refresh.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        interaction.edit_original_response.assert_awaited_once()
        self.assertTrue(interaction.edit_original_response.await_args.kwargs["content"].startswith("# "))
        refreshed = interaction.edit_original_response.await_args.kwargs["view"]
        self.assertEqual(
            [
                child.placeholder
                for child in refreshed.children
                if isinstance(child, BrainActiveControlSelect | BrainUpcomingEventsSelect)
            ],
            [f"{UPCOMING_EVENTS_LABEL}: 1", f"{ACTIVE_TASKS_LABEL}: 1", f"{SUPPLIES_LABEL}: 1"],
        )

    async def test_upcoming_event_select_opens_detail_message(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [{"title": "Clinic", "date": "2026-08-22", "time": "10:50", "ownerLabel": "Family"}],
            [],
            [],
            [],
        )
        event_select = next(child for child in view.children if isinstance(child, BrainUpcomingEventsSelect))
        event_select._values = ["0"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await event_select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertEqual(content, "## Clinic\n- 2026-08-22 · 10:50 · 𝘧𝘢𝘮𝘪𝘭𝘺")

    async def test_upcoming_event_select_descriptions_use_display_owner_markers(self) -> None:
        view = BrainActiveControlView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            self.active_control_settings(),
            [
                {"title": "Market Day", "date": "2026-08-25", "ownerLabel": "GDD_ZiN"},
                {"title": "School", "date": "2026-08-26", "ownerLabel": "Family"},
            ],
            [],
            [],
            [],
        )
        event_select = next(child for child in view.children if isinstance(child, BrainUpcomingEventsSelect))

        self.assertEqual(event_select.options[0].description, "2026-08-25 · 𝘎𝘋𝘋𝙕𝘪𝙉")
        self.assertEqual(event_select.options[1].description, "2026-08-26 · 𝘧𝘢𝘮𝘪𝘭𝘺")

    async def test_memo_search_select_opens_selected_memo_as_new_message(self) -> None:
        view = BrainMemoSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "rustdesk",
            [{"name": "memos/42", "snippet": "# Rustdesk", "tags": ["server"]}],
        )
        search_message = SimpleNamespace(id=900, delete=AsyncMock())
        view.bind_message(search_message)  # type: ignore[arg-type]
        select = next(child for child in view.children if isinstance(child, BrainMemoSearchSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertEqual(content, "# Rustdesk\nUse Tailscale.")
        self.assertIn("view", interaction.followup.send.await_args.kwargs)
        search_message.delete.assert_awaited_once()

    async def test_document_search_select_opens_selected_document_as_new_message(self) -> None:
        view = BrainDocumentSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "보험",
            [{"id": 42, "title": "Insurance"}],
            paperless_public_url="https://paperless.example",
        )
        search_message = SimpleNamespace(id=901, delete=AsyncMock())
        view.bind_message(search_message)  # type: ignore[arg-type]
        select = next(child for child in view.children if isinstance(child, BrainDocumentSearchSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn("## Insurance receipt", content)
        self.assertNotIn("Documents search", content)
        self.assertIn("Insurance receipt", content)
        opened_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(opened_view, BrainOpenedDocumentView)
        self.assertEqual([item.label for item in opened_view.children], ["Close", "Open document"])
        search_message.delete.assert_awaited_once()

    async def test_combined_paperless_button_switches_to_embed_list(self) -> None:
        view = BrainCombinedSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "보험",
            [{"name": "memos/42", "snippet": "Memo"}],
            [{"id": index + 1, "title": f"Document {index + 1}"} for index in range(25)],
            document_count=30,
            document_total=30,
            paperless_public_url="https://paperless.example",
        )
        button = next(child for child in view.children if isinstance(child, BrainCombinedSearchFullButton) and child.label == "Paperless")
        source_message = SimpleNamespace(id=903)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            message=source_message,
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )

        await button.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.edit_message.assert_awaited_once()
        kwargs = interaction.response.edit_message.await_args.kwargs
        self.assertEqual(kwargs["content"], "")
        self.assertEqual(kwargs["embed"].title, "Paperless · 보험")
        self.assertIn("30 results in 30 documents", kwargs["embed"].description)
        self.assertIn("[open](https://paperless.example/documents/1/details)", kwargs["embed"].fields[0].value)
        self.assertIsInstance(kwargs["view"], BrainDocumentSearchView)

    async def test_brain_search_window_shows_expired_notice_on_timeout(self) -> None:
        view = BrainMemoSearchView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            "rustdesk",
            [{"name": "memos/42", "snippet": "# Rustdesk"}],
        )
        search_message = SimpleNamespace(id=902, edit=AsyncMock())
        view.bind_message(search_message)  # type: ignore[arg-type]

        await view.on_timeout()

        search_message.edit.assert_awaited_once()
        self.assertEqual(
            search_message.edit.await_args.kwargs["content"],
            "Search result of rustdesk expired after 10 mins.",
        )
        self.assertIsNone(search_message.edit.await_args.kwargs["view"])

    def test_memo_confirm_buttons_match_governor_labels(self) -> None:
        edit = BrainMemoEditConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]
        delete = BrainMemoDeleteConfirmView(FakeGovernorTools(), 200, "memos/42", "# Memo")  # type: ignore[arg-type]

        self.assertEqual([item.label for item in edit.children], ["Edit Memo", "Cancel"])
        self.assertEqual([item.label for item in delete.children], ["Delete Memo", "Cancel"])

    async def test_memo_delete_confirm_defers_before_governor_write(self) -> None:
        tools = FakeGovernorTools()
        view = BrainMemoDeleteConfirmView(tools, 200, "memos/42", "# Memo")  # type: ignore[arg-type]
        order: list[str] = []

        async def defer() -> None:
            order.append("defer")

        async def propose_memo_delete_by_name(name: str, *, actor_id: int, idempotency_key: str):
            order.append("propose")
            return {"confirmationId": "confirm-memo-delete", "memo": {"name": name}}

        tools.propose_memo_delete_by_name = propose_memo_delete_by_name  # type: ignore[method-assign]
        interaction = SimpleNamespace(
            id=1003,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(side_effect=defer), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(order, ["defer", "propose"])
        interaction.edit_original_response.assert_awaited_once()
        self.assertIn("Deleted at", interaction.edit_original_response.await_args.kwargs["content"])

    async def test_memo_undo_delete_defers_before_governor_write(self) -> None:
        tools = FakeGovernorTools()
        view = BrainDeletedMemoView(tools, 200, "# Memo")  # type: ignore[arg-type]
        order: list[str] = []

        async def defer() -> None:
            order.append("defer")

        async def propose_memo_create(request, *, actor_id: int, idempotency_key: str):
            order.append("propose")
            return {"confirmationId": "confirm-memo-create", "memo": {"content": request.content}}

        tools.propose_memo_create = propose_memo_create  # type: ignore[method-assign]
        interaction = SimpleNamespace(
            id=1004,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(side_effect=defer), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(order, ["defer", "propose"])
        interaction.edit_original_response.assert_awaited_once()
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["content"], "# Memo")

    async def test_completed_task_select_sends_reopen_confirmation_message(self) -> None:
        tools = FakeGovernorTools()
        view = BrainCompletedTasksView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.COMPLETED_TASKS, profile="supplies"),
            [{"title": "Soap", "completedDate": "2026-08-15"}],
        )
        select = next(child for child in view.children if isinstance(child, BrainCompletedTasksSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            id=777,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        request, actor_id, idempotency_key = tools.task_action_calls[0]
        self.assertEqual(request.task_title, "Soap")
        self.assertEqual(request.action, "reopen")
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "brain-task-reopen-777")
        interaction.response.defer.assert_awaited_once()
        content = interaction.followup.send.await_args.args[0]
        self.assertIn("## Confirm task action", content)
        self.assertIn("- action: reopen", content)

    async def test_active_task_select_sends_action_buttons(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTasksView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            [{"title": "Soap"}],
        )
        select = next(child for child in view.children if isinstance(child, BrainActiveTasksSelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            id=888,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        self.assertEqual(interaction.followup.send.await_args.args[0], "## Soap")
        action_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(action_view, BrainActiveTaskActionsView)
        self.assertEqual([item.label for item in action_view.children], ["Complete", "Edit", "Delete", "Close"])

    async def test_active_task_service_paginates_25_items(self) -> None:
        tasks = [{"title": f"Task {index:02d}"} for index in range(1, 28)]
        view = BrainActiveTasksView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS),
            tasks,
        )
        select = next(child for child in view.children if isinstance(child, BrainActiveTasksSelect))

        self.assertIn("- active: 27", view.content())
        self.assertIn("- showing: 1-25", view.content())
        self.assertEqual(len(select.options), 25)
        self.assertEqual(select.placeholder, "Active Tasks 1-25")

    async def test_active_task_service_next_page_edits_same_message(self) -> None:
        tasks = [{"title": f"Task {index:02d}"} for index in range(1, 28)]
        view = BrainActiveTasksView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS),
            tasks,
        )
        next_button = next(child for child in view.children if getattr(child, "label", "") == "→")
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await next_button.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertIn("- showing: 26-27", kwargs["content"])
        refreshed = kwargs["view"]
        select = next(child for child in refreshed.children if isinstance(child, BrainActiveTasksSelect))
        self.assertEqual(len(select.options), 2)
        self.assertEqual(select.placeholder, "Active Tasks 26-27")

    async def test_task_service_history_button_loads_month_archive(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTasksView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS),
            [{"title": "Active"}],
        )
        history = next(child for child in view.children if getattr(child, "label", "") == "History")
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await history.callback(interaction)  # type: ignore[arg-type,union-attr]

        interaction.response.defer.assert_awaited_once()
        kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertIn("## 𝓣𝓪𝓼𝓴𝓼 𝓗𝓲𝓼𝓽𝓸𝓻𝔂", kwargs["content"])
        self.assertIn("### ", kwargs["content"])
        self.assertIn(" • Completed: 30", kwargs["content"])
        self.assertNotIn("- completed:", kwargs["content"])
        self.assertNotIn("- showing:", kwargs["content"])
        self.assertIn("- 15.토 - ~~Done 01~~", kwargs["content"])
        refreshed = kwargs["view"]
        self.assertTrue(any(isinstance(child, BrainTaskHistorySelect) for child in refreshed.children))
        self.assertIn("Page 1/2", [getattr(child, "label", "") for child in refreshed.children])
        self.assertEqual([getattr(child, "label", "") for child in refreshed.children if getattr(child, "label", "")][-2:], ["Active", "Close"])

    async def test_supplies_history_service_omits_dates(self) -> None:
        view = BrainActiveTasksView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.COMPLETED_TASKS, profile="supplies"),
            [{"uid": "DONE-1", "title": "Soap", "completedDate": "2026-08-15"}],
            mode="history",
        )

        content = view.content()

        self.assertIn("## 𝓢𝓾𝓹𝓹𝓵𝓲𝓮𝓼 𝓗𝓲𝓼𝓽𝓸𝓻𝔂", content)
        self.assertIn("### ", content)
        self.assertIn(" • Completed: 1", content)
        self.assertIn("- ~~Soap~~", content)
        self.assertNotIn("2026-08-15", content)
        self.assertNotIn("15.", content)

    async def test_task_history_select_sends_history_action_buttons(self) -> None:
        view = BrainActiveTasksView(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.COMPLETED_TASKS),
            [{"uid": "DONE-1", "title": "Done task", "completedDate": "2026-08-15"}],
            mode="history",
        )
        select = next(child for child in view.children if isinstance(child, BrainTaskHistorySelect))
        select._values = ["0"]
        interaction = SimpleNamespace(
            id=889,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await select.callback(interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_awaited_once()
        self.assertEqual(interaction.followup.send.await_args.args[0], "## ~~Done task~~\n- completed: 2026-08-15")
        action_view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(action_view, BrainCompletedTaskActionsView)
        self.assertEqual([item.label for item in action_view.children], ["Undo", "Make New", "Delete", "Close"])

    async def test_completed_task_make_new_button_sends_create_confirmation(self) -> None:
        tools = FakeGovernorTools()
        view = BrainCompletedTaskActionsView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.COMPLETED_TASKS, profile="supplies"),
            {"uid": "SUPPLY-DONE-1", "title": "Soap"},
        )
        interaction = SimpleNamespace(
            id=890,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )

        await view.children[1].callback(interaction)  # type: ignore[arg-type,union-attr]

        request, actor_id, idempotency_key = tools.task_create_calls[0]
        self.assertEqual(request.title, "Soap")
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "brain-task-make-new-890")
        content = interaction.response.edit_message.await_args.kwargs["content"]
        self.assertIn("Confirm New Supply", content)
        self.assertIn("## Soap", content)

    async def test_active_task_complete_button_sends_confirmation(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTaskActionsView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"uid": "TASK-1", "title": "Call mom"},
        )
        interaction = SimpleNamespace(
            id=999,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        request, actor_id, idempotency_key = tools.task_action_calls[0]
        self.assertEqual(request.uid, "TASK-1")
        self.assertEqual(request.task_title, "Call mom")
        self.assertEqual(request.action, "complete")
        self.assertEqual(request.profile, "family")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "brain-task-complete-999")
        content = interaction.response.edit_message.await_args.kwargs["content"]
        self.assertIn("## Confirm task action", content)
        self.assertIn("- action: complete", content)

    async def test_active_task_delete_button_sends_confirmation(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTaskActionsView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            {"uid": "SUPPLY-1", "title": "Soap"},
        )
        interaction = SimpleNamespace(
            id=1000,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )

        await view.children[2].callback(interaction)  # type: ignore[arg-type,union-attr]

        request, _, idempotency_key = tools.task_action_calls[0]
        self.assertEqual(request.uid, "SUPPLY-1")
        self.assertEqual(request.task_title, "Soap")
        self.assertEqual(request.action, "delete")
        self.assertEqual(request.profile, "supplies")
        self.assertEqual(idempotency_key, "brain-task-delete-1000")

    async def test_active_task_edit_button_opens_prefilled_modal(self) -> None:
        tools = FakeGovernorTools()
        view = BrainActiveTaskActionsView(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"uid": "TASK-1", "title": "Call mom", "memo": "weekly", "due": "2026-08-17", "dueTime": "10:00"},
        )
        interaction = SimpleNamespace(
            id=1001,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock()),
        )

        await view.children[1].callback(interaction)  # type: ignore[arg-type,union-attr]

        modal = interaction.response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, BrainTaskEditModal)
        self.assertEqual(len(modal.children), 5)
        self.assertEqual(str(modal.title_input.default), "Call mom")
        self.assertEqual(str(modal.memo_input.default), "weekly")

    async def test_supplies_edit_modal_has_no_due_fields(self) -> None:
        modal = BrainTaskEditModal(
            FakeGovernorTools(),  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="supplies"),
            {"uid": "SUPPLY-1", "title": "Soap", "memo": "bath"},
        )

        self.assertEqual(len(modal.children), 2)

    async def test_task_edit_modal_sends_confirmation(self) -> None:
        tools = FakeGovernorTools()
        modal = BrainTaskEditModal(
            tools,  # type: ignore[arg-type]
            200,
            ToolRequest(ToolKind.ACTIVE_TASKS, profile="family"),
            {"uid": "TASK-1", "title": "Call mom", "memo": "weekly", "due": "2026-08-17", "dueTime": "10:00"},
        )
        modal.title_input._value = "Call dad"
        modal.memo_input._value = "monthly"
        modal.due_date_input._value = "2026-08-20"
        modal.due_time_input._value = "14:30"
        modal.priority_input._value = "1"
        interaction = SimpleNamespace(
            id=1002,
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        await modal.on_submit(interaction)  # type: ignore[arg-type]

        request, actor_id, idempotency_key = tools.task_edit_calls[0]
        self.assertEqual(request.uid, "TASK-1")
        self.assertEqual(request.task_title, "Call mom")
        self.assertEqual(request.title, "Call dad")
        self.assertEqual(request.memo, "monthly")
        self.assertEqual(request.due_date, "2026-08-20")
        self.assertEqual(request.due_time, "14:30")
        self.assertEqual(request.priority, "1")
        self.assertEqual(actor_id, 200)
        self.assertEqual(idempotency_key, "brain-task-edit-1002")
        content = interaction.response.send_message.await_args.args[0]
        self.assertIn("## Confirm task edit", content)

    async def test_task_create_confirm_defers_before_approving(self) -> None:
        tools = FakeGovernorTools()
        view = TaskCreateConfirmationView(tools, 200, "confirm-create-1")  # type: ignore[arg-type]
        order: list[str] = []

        async def defer() -> None:
            order.append("defer")

        async def approve_confirmation(confirmation_id: str, *, actor_id: int):
            order.append("approve")
            return {"task": {"title": "오도리 문고리", "due": "", "dueTime": ""}}

        tools.approve_confirmation = approve_confirmation  # type: ignore[method-assign]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            response=SimpleNamespace(defer=AsyncMock(side_effect=defer), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        await view.children[0].callback(interaction)  # type: ignore[arg-type,union-attr]

        self.assertEqual(order, ["defer", "approve"])
        interaction.edit_original_response.assert_awaited_once()
        content = interaction.edit_original_response.await_args.kwargs["content"]
        self.assertEqual(content, "Task added.")
        self.assertIsNone(interaction.edit_original_response.await_args.kwargs["view"])


if __name__ == "__main__":
    unittest.main()
