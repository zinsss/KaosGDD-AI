from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any

import discord

from .discord_active_control_views import (
    BrainActiveControlView,
    BrainServiceMenuView,
    _write_active_control_message_id,
)
from .discord_formatting import (
    ACTIVE_CONTROL_HISTORY_LIMIT,
    ACTIVE_CONTROL_MARKER,
    KST,
    SERVICE_MENU_MARKER,
    _active_control_month_file_for,
    _event_results,
    _import_results,
    _task_results,
    render_active_control_message,
)
from .discord_view_helpers import NO_MENTIONS
from .tool_intent import ToolKind, ToolRequest

LOGGER = logging.getLogger(__name__)


def _is_transient_brain_message(content: str) -> bool:
    normalized = content.strip()
    if not normalized:
        return False
    if normalized.startswith(ACTIVE_CONTROL_MARKER) or normalized == SERVICE_MENU_MARKER:
        return False
    if normalized.startswith(("Confirm ", "## Confirm ")):
        return True
    if "실패했어요." in normalized or "취소했어요." in normalized:
        return True
    return normalized in {
        "Task added.",
        "Supply added.",
        "일정 저장했어요.",
        "메모 저장했어요.",
        "할 일 수정했어요.",
        "할 일 삭제했어요.",
        "할 일 완료했어요.",
        "할 일 다시 열었어요.",
        "비품 수정했어요.",
        "비품 삭제했어요.",
        "비품 완료했어요.",
        "비품 다시 열었어요.",
    }


class BrainActiveControlMixin:
    governor_tools: Any
    settings: Any
    user: Any
    _active_control_message_id: int
    _active_control_service_message_id: int

    async def _reload_active_control_from_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.warning("Failed to delete active control reload command")
        await self._ensure_active_control_message(move_to_bottom=True)

    async def _ensure_active_control_message(self, *, move_to_bottom: bool = False) -> None:
        if self.governor_tools is None or self.user is None:
            return
        try:
            channel = self.get_channel(self.settings.brain_channel_id) or await self.fetch_channel(self.settings.brain_channel_id)  # type: ignore[attr-defined]
            if not isinstance(channel, discord.TextChannel | discord.Thread):
                return
            events, tasks, supplies, imports = await self._active_control_items()
            current = datetime.now(KST)
            month_file = await self._active_control_month_file(today=current.date())
            content = render_active_control_message(events, tasks, supplies, now=current)
            view = BrainActiveControlView(self.governor_tools, self.settings, events, tasks, supplies, imports)
            message = await self._find_active_control_message(channel)
            service_message = await self._find_active_control_service_message(channel)
            if move_to_bottom:
                await self._delete_recent_transient_brain_messages(channel)
                if message is not None:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        LOGGER.warning("Failed to delete old active control message")
                    message = None
                if service_message is not None:
                    try:
                        await service_message.delete()
                    except discord.HTTPException:
                        LOGGER.warning("Failed to delete old active control service message")
                    service_message = None
            if message is None:
                kwargs: dict[str, Any] = {"content": content, "view": view, "allowed_mentions": NO_MENTIONS}
                if month_file is not None:
                    kwargs["file"] = month_file
                message = await channel.send(**kwargs)
            else:
                kwargs = {"content": content, "view": view, "allowed_mentions": NO_MENTIONS}
                if month_file is not None:
                    kwargs["attachments"] = [month_file]
                await message.edit(**kwargs)
            self._active_control_message_id = int(message.id)
            service_view = BrainServiceMenuView(self.governor_tools, self.settings)
            if service_message is None:
                service_message = await channel.send(SERVICE_MENU_MARKER, view=service_view, allowed_mentions=NO_MENTIONS)
            else:
                await service_message.edit(content=SERVICE_MENU_MARKER, view=service_view, allowed_mentions=NO_MENTIONS)
            self._active_control_service_message_id = int(service_message.id)
            try:
                _write_active_control_message_id(
                    self.settings.active_control_state_path,
                    self._active_control_message_id,
                    self._active_control_service_message_id,
                )
            except OSError as exc:
                LOGGER.warning("Active control message state write failed: %s", exc)
        except Exception as exc:
            LOGGER.warning("Active control message refresh failed: %s", exc)

    async def _delete_recent_transient_brain_messages(self, channel: discord.TextChannel | discord.Thread) -> None:
        if self.user is None:
            return
        async for message in channel.history(limit=ACTIVE_CONTROL_HISTORY_LIMIT):
            if message.author.id != self.user.id:
                continue
            if not _is_transient_brain_message(str(message.content or "")):
                continue
            try:
                await message.delete()
            except discord.HTTPException:
                LOGGER.warning("Failed to delete transient Brain message %s", getattr(message, "id", ""))

    async def _find_active_control_message(self, channel: discord.TextChannel | discord.Thread) -> discord.Message | None:
        if self._active_control_message_id:
            try:
                return await channel.fetch_message(self._active_control_message_id)
            except discord.HTTPException:
                self._active_control_message_id = 0
        async for message in channel.history(limit=ACTIVE_CONTROL_HISTORY_LIMIT):
            content = str(message.content or "")
            if message.author.id == self.user.id and content.startswith(ACTIVE_CONTROL_MARKER):
                return message
        return None

    async def _find_active_control_service_message(self, channel: discord.TextChannel | discord.Thread) -> discord.Message | None:
        if self._active_control_service_message_id:
            try:
                return await channel.fetch_message(self._active_control_service_message_id)
            except discord.HTTPException:
                self._active_control_service_message_id = 0
        async for message in channel.history(limit=ACTIVE_CONTROL_HISTORY_LIMIT):
            content = str(message.content or "")
            if message.author.id == self.user.id and content == SERVICE_MENU_MARKER:
                return message
        return None

    async def _active_control_items(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if self.governor_tools is None:
            return [], [], [], []
        events_payload = await self.governor_tools.fetch(
            ToolRequest(ToolKind.UPCOMING_EVENTS, profile=self.settings.governor_tools_profile)
        )
        tasks_payload = await self.governor_tools.fetch(ToolRequest(ToolKind.ACTIVE_TASKS, profile=self.settings.governor_tools_profile))
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

    async def _active_control_month_file(self, *, today: date) -> discord.File | None:
        return await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            today=today,
        )
