from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any

import discord

from .config import Settings
from .discord_calendar_views import BrainCalendarMonthView
from .discord_content_views import (
    BrainDocumentSearchView,
    BrainMemoSearchView,
    _linked_document_results,
)
from .discord_fax_mail_views import BrainFaxMailView, send_fax_mail_selection
from .discord_formatting import (
    ACTIVE_CONTROL_LIMIT,
    ACTIVE_TASKS_LABEL,
    CALENDAR_LABEL,
    FAX_MAIL_LABEL,
    KST,
    MEMOS_LABEL,
    MEMOS_TITLE,
    PAPERLESS_LABEL,
    PAPERLESS_TITLE,
    SERVICE_MENU_MARKER,
    SUPPLIES_LABEL,
    TASKS_SERVICE_BUTTON_LABEL,
    UPCOMING_EVENTS_LABEL,
    _active_control_month_file_for,
    _active_fax_mail_imports,
    _event_option_description,
    _event_option_label,
    _event_results,
    _fax_mail_results,
    _has_overdue_tasks,
    _import_option_description,
    _import_option_label,
    _import_results,
    _render_active_task_selection,
    _render_document_list_message,
    _render_event_selection,
    _render_memo_list_message,
    _payload_count,
    _task_option_description,
    _task_option_label,
    _task_results,
    render_active_control_message,
)
from .discord_task_views import BrainActiveTaskActionsView, BrainActiveTasksView
from .discord_view_helpers import NO_MENTIONS, BrainCloseOnlyServiceView, _bind_view_message, _followup_with_bound_view
from .governor_tools import GovernorToolClient, GovernorToolError, SEARCH_RESULT_LIMIT, search_results
from .tool_intent import ToolKind, ToolRequest

LOGGER = logging.getLogger(__name__)


def _tool_failed(action: str) -> str:
    return f"{action} 실패했어요."


async def _delete_open_service_message(settings: Settings, interaction: discord.Interaction) -> None:
    state_path = getattr(settings, "active_control_state_path", "")
    message_id = _read_open_service_message_id(state_path)
    if not message_id:
        return
    try:
        channel = await _interaction_brain_channel(settings, interaction)
        if channel is None:
            return
        message = await channel.fetch_message(message_id)
        await message.delete()
    except discord.HTTPException:
        LOGGER.info("Open Brain service message %s was already unavailable", message_id)
    finally:
        _write_active_control_message_id(state_path, 0, open_service_message_id=0)


async def _send_single_service_message(
    settings: Settings,
    interaction: discord.Interaction,
    *args: Any,
    **kwargs: Any,
) -> discord.Message | None:
    await _delete_open_service_message(settings, interaction)
    kwargs.setdefault("allowed_mentions", NO_MENTIONS)
    kwargs.setdefault("wait", True)
    message = await interaction.followup.send(*args, **kwargs)
    view = kwargs.get("view")
    _bind_view_message(view, message)
    bind_close_callback = getattr(view, "bind_close_callback", None)
    state_path = getattr(settings, "active_control_state_path", "")
    if callable(bind_close_callback) and state_path:
        bind_close_callback(lambda: _write_active_control_message_id(state_path, 0, open_service_message_id=0))
    try:
        message_id = int(getattr(message, "id", 0) or 0)
    except (TypeError, ValueError):
        message_id = 0
    if message_id > 0:
        _write_active_control_message_id(
            getattr(settings, "active_control_state_path", ""),
            0,
            open_service_message_id=message_id,
        )
    return message if isinstance(message, discord.Message) else None


async def _interaction_brain_channel(
    settings: Settings,
    interaction: discord.Interaction,
) -> Any | None:
    channel = getattr(interaction, "channel", None)
    if isinstance(channel, discord.TextChannel | discord.Thread):
        return channel
    if callable(getattr(channel, "fetch_message", None)):
        return channel
    client = getattr(interaction, "client", None)
    if client is None:
        return None
    get_channel = getattr(client, "get_channel", None)
    if callable(get_channel):
        channel = get_channel(settings.brain_channel_id)
        if isinstance(channel, discord.TextChannel | discord.Thread):
            return channel
        if callable(getattr(channel, "fetch_message", None)):
            return channel
    fetch_channel = getattr(client, "fetch_channel", None)
    if callable(fetch_channel):
        try:
            channel = await fetch_channel(settings.brain_channel_id)
        except discord.HTTPException:
            return None
        if isinstance(channel, discord.TextChannel | discord.Thread):
            return channel
        if callable(getattr(channel, "fetch_message", None)):
            return channel
    return None


def _read_active_control_message_id(path: str) -> int:
    return _read_active_control_state_value(path, "messageId")


def _read_active_control_service_message_id(path: str) -> int:
    return _read_active_control_state_value(path, "serviceMessageId")


def _read_open_service_message_id(path: str) -> int:
    return _read_active_control_state_value(path, "openServiceMessageId")


def _read_active_control_state_value(path: str, key: str) -> int:
    if not path:
        return 0
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    try:
        message_id = int(payload.get(key, 0))
    except (TypeError, ValueError):
        return 0
    return message_id if message_id > 0 else 0


def _write_active_control_message_id(
    path: str,
    message_id: int,
    service_message_id: int = 0,
    *,
    open_service_message_id: int | None = None,
) -> None:
    if not path or (message_id <= 0 and service_message_id <= 0 and open_service_message_id is None):
        return
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, int] = {}
    try:
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload.update(
                {
                    key: int(value)
                    for key, value in existing.items()
                    if key in {"messageId", "serviceMessageId", "openServiceMessageId"}
                }
            )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        payload = {}
    if message_id > 0:
        payload["messageId"] = message_id
    if service_message_id > 0:
        payload["serviceMessageId"] = service_message_id
    if open_service_message_id is not None:
        if open_service_message_id > 0:
            payload["openServiceMessageId"] = open_service_message_id
        else:
            payload.pop("openServiceMessageId", None)
    tmp_path = state_path.with_suffix(f"{state_path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp_path.replace(state_path)


class BrainActiveControlView(discord.ui.View):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        settings: Settings,
        events: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        supplies: list[dict[str, Any]],
        imports: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.settings = settings
        self.events = events[:ACTIVE_CONTROL_LIMIT]
        self.tasks = tasks[:ACTIVE_CONTROL_LIMIT]
        self.supplies = supplies[:ACTIVE_CONTROL_LIMIT]
        self.imports = _active_fax_mail_imports(imports)[:ACTIVE_CONTROL_LIMIT]
        self.add_item(BrainUpcomingEventsSelect(self, self.events))
        self.add_item(BrainActiveControlSelect(self, "tasks", self.tasks))
        self.add_item(BrainActiveControlSelect(self, "supplies", self.supplies))
        self.add_item(BrainImportSelect(self, self.imports))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == self.settings.guild_id
            and interaction.channel_id == self.settings.brain_channel_id
            and int(interaction.user.id) in self.settings.allowed_user_ids
        ):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def request_for_kind(self, kind: str) -> ToolRequest:
        if kind == "supplies":
            return ToolRequest(
                ToolKind.ACTIVE_TASKS,
                profile="supplies",
                collection_id=self.settings.governor_tools_supplies_collection_id,
            )
        return ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile)

    async def refresh_items(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        events_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.UPCOMING_EVENTS, profile=self.settings.governor_tools_profile)
        )
        tasks_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile)
        )
        supplies_payload = await self.governor_tools.fetch(
            ToolRequest(
                ToolKind.ACTIVE_TASKS,
                profile="supplies",
                collection_id=self.settings.governor_tools_supplies_collection_id,
            )
        )
        imports_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.RECENT_IMPORTS, profile=self.settings.governor_tools_profile)
        )
        return _event_results(events_payload), _task_results(tasks_payload), _task_results(supplies_payload), _import_results(imports_payload)

    @discord.ui.button(label="Reload", style=discord.ButtonStyle.primary, row=4)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            events, tasks, supplies, imports = await self.refresh_items()
        except GovernorToolError as exc:
            LOGGER.warning("Active control refresh failed: %s", exc)
            await interaction.followup.send(_tool_failed("Active 갱신"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        current = datetime.now(KST)
        kwargs: dict[str, Any] = {
            "content": render_active_control_message(events, tasks, supplies, now=current),
            "view": BrainActiveControlView(self.governor_tools, self.settings, events, tasks, supplies, imports),
            "allowed_mentions": NO_MENTIONS,
        }
        month_file = await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            today=current.date(),
        )
        if month_file is not None:
            kwargs["attachments"] = [month_file]
        await interaction.edit_original_response(**kwargs)


class BrainServiceMenuView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, settings: Settings) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.settings = settings
        self.add_item(BrainServiceMenuSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == self.settings.guild_id
            and interaction.channel_id == self.settings.brain_channel_id
            and int(interaction.user.id) in self.settings.allowed_user_ids
        ):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def open_calendar(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        current = datetime.now(KST).date()
        view = BrainCalendarMonthView(
            self.governor_tools,
            self.settings,
            anchor_date=current,
            year=current.year,
            month=current.month,
            mode="weekly",
        )
        kwargs: dict[str, Any] = {
            "content": await view.weekly_content(),
            "view": view,
            "allowed_mentions": NO_MENTIONS,
        }
        await _send_single_service_message(self.settings, interaction, **kwargs)

    async def open_tasks(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.fetch(
                ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile)
            )
        except GovernorToolError as exc:
            LOGGER.warning("Tasks service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("할 일 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        tasks = _task_results(payload)
        view = BrainActiveTasksView(
            self.governor_tools,
            int(interaction.user.id),
            ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile),
            tasks,
        )
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content(),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_supplies(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        request = ToolRequest(
            ToolKind.ACTIVE_TASKS,
            profile="supplies",
            collection_id=self.settings.governor_tools_supplies_collection_id,
        )
        try:
            payload = await self.governor_tools.fetch(request)
        except GovernorToolError as exc:
            LOGGER.warning("Supplies service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("비품 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        supplies = _task_results(payload)
        view = BrainActiveTasksView(self.governor_tools, int(interaction.user.id), request, supplies)
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content(),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_paperless(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.documents("", page=1, limit=SEARCH_RESULT_LIMIT)
        except GovernorToolError as exc:
            LOGGER.warning("Paperless service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("Paperless 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        results = _linked_document_results(search_results(payload), self.settings.paperless_public_url)
        result_count = _payload_count(payload, "resultCount", "count", fallback=len(results))
        total_count = _payload_count(payload, "totalCount", "total", fallback=result_count)
        page = _payload_count(payload, "page", fallback=1)
        page_size = _payload_count(payload, "pageSize", "page_size", fallback=SEARCH_RESULT_LIMIT)
        view: discord.ui.View = BrainDocumentSearchView(
            self.governor_tools,
            int(interaction.user.id),
            "",
            results,
            result_count=result_count,
            total_count=total_count,
            page=page,
            page_size=page_size,
            paperless_public_url=self.settings.paperless_public_url,
            close_on_timeout=True,
        ) if results else BrainCloseOnlyServiceView()
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content()  # type: ignore[attr-defined]
            if isinstance(view, BrainDocumentSearchView)
            else _render_document_list_message(
                "",
                results,
                result_count=result_count,
                total_count=total_count,
                page=page,
                page_size=page_size,
                searched=False,
            ),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_memos(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        request = ToolRequest(ToolKind.MEMO_SEARCH, "")
        try:
            payload = await self.governor_tools.fetch(request)
        except GovernorToolError as exc:
            LOGGER.warning("Memos service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("Memos 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        results = search_results(payload)
        view = BrainMemoSearchView(
            self.governor_tools,
            int(interaction.user.id),
            "",
            results,
            result_count=_payload_count(payload, "resultCount", "count", fallback=len(results)),
            total_count=_payload_count(payload, "totalCount", fallback=len(results)),
            memos_public_url=self.settings.memos_public_url,
            close_on_timeout=True,
        ) if results else BrainCloseOnlyServiceView()
        await _send_single_service_message(
            self.settings,
            interaction,
            view.content() if isinstance(view, BrainMemoSearchView) else _render_memo_list_message(
                "",
                results,
                result_count=_payload_count(payload, "resultCount", "count", fallback=len(results)),
                total_count=_payload_count(payload, "totalCount", fallback=len(results)),
                searched=False,
            ),
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    async def open_fax_mail(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            payload = await self.governor_tools.fetch(
                ToolRequest(ToolKind.RECENT_IMPORTS, profile=self.settings.governor_tools_profile)
            )
        except GovernorToolError as exc:
            LOGGER.warning("Fax Mail service message failed: %s", exc)
            await interaction.followup.send(_tool_failed("Fax Mail 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        imports = _fax_mail_results(payload, mode="incoming")
        view = BrainFaxMailView(
            self.governor_tools,
            int(interaction.user.id),
            self.settings,
            imports,
            mode="incoming_fax",
        )
        await _send_single_service_message(self.settings, interaction, view.content(), view=view, allowed_mentions=NO_MENTIONS)


class BrainServiceMenuSelect(discord.ui.Select):
    def __init__(self, service_menu: BrainServiceMenuView) -> None:
        self.service_menu = service_menu
        super().__init__(
            placeholder="Select one.",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=CALENDAR_LABEL, value="calendar"),
                discord.SelectOption(label=TASKS_SERVICE_BUTTON_LABEL, value="tasks"),
                discord.SelectOption(label=SUPPLIES_LABEL, value="supplies"),
                discord.SelectOption(label=PAPERLESS_LABEL, value="paperless"),
                discord.SelectOption(label=MEMOS_LABEL, value="memos"),
                discord.SelectOption(label=FAX_MAIL_LABEL, value="fax_mail"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0] if self.values else ""
        if selected == "calendar":
            await self.service_menu.open_calendar(interaction)
        elif selected == "tasks":
            await self.service_menu.open_tasks(interaction)
        elif selected == "supplies":
            await self.service_menu.open_supplies(interaction)
        elif selected == "paperless":
            await self.service_menu.open_paperless(interaction)
        elif selected == "memos":
            await self.service_menu.open_memos(interaction)
        elif selected == "fax_mail":
            await self.service_menu.open_fax_mail(interaction)
        else:
            await interaction.response.send_message("Unknown service.", ephemeral=True, allowed_mentions=NO_MENTIONS)


class BrainUpcomingEventsSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveControlView, events: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.events = events
        options = [
            discord.SelectOption(
                label=_event_option_label(event),
                description=_event_option_description(event) or None,
                value=str(index),
            )
            for index, event in enumerate(events[:ACTIVE_CONTROL_LIMIT])
        ]
        disabled = not options
        if disabled:
            options = [discord.SelectOption(label="No upcoming events", value="empty")]
        super().__init__(placeholder=f"{UPCOMING_EVENTS_LABEL}: {len(events)}", min_values=1, max_values=1, options=options, row=0, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            event = self.events[int(self.values[0])]
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Upcoming event selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("일정 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.followup.send(_render_event_selection(event), allowed_mentions=NO_MENTIONS)


class BrainActiveControlSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveControlView, kind: str, tasks: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.kind = kind
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(
                    task,
                    include_completed=False,
                    supplies=kind == "supplies",
                )
                or None,
                value=str(index),
            )
            for index, task in enumerate(tasks[:ACTIVE_CONTROL_LIMIT])
        ]
        label = SUPPLIES_LABEL if kind == "supplies" else ACTIVE_TASKS_LABEL
        placeholder = f"{label}: {len(tasks)}"
        if kind == "tasks" and _has_overdue_tasks(tasks):
            placeholder = f"{placeholder} ★"
        row = 2 if kind == "supplies" else 1
        disabled = not options
        if disabled:
            label = "No active supplies" if kind == "supplies" else "No active tasks"
            options = [discord.SelectOption(label=label, value="empty")]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, row=row, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            items = self.parent_view.supplies if self.kind == "supplies" else self.parent_view.tasks
            task = items[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Active control selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("항목 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            _render_active_task_selection(title, task, supplies=self.kind == "supplies"),
            view=BrainActiveTaskActionsView(
                self.parent_view.governor_tools,
                int(interaction.user.id),
                self.parent_view.request_for_kind(self.kind),
                task,
            ),
        )


class BrainImportSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveControlView, imports: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.imports = imports
        options = [
            discord.SelectOption(
                label=_import_option_label(item),
                description=_import_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(imports[:ACTIVE_CONTROL_LIMIT])
        ]
        disabled = not options
        if disabled:
            options = [discord.SelectOption(label="No new fax/mail imports", value="empty")]
        super().__init__(placeholder=f"{FAX_MAIL_LABEL}: {len(imports)}", min_values=1, max_values=1, options=options, row=3, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.imports[int(self.values[0])]
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Import selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("Import 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await send_fax_mail_selection(self.parent_view.governor_tools, interaction, item)
