from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Mapping

import discord
from kaos_governor.calendar import CalendarAdapterClient

from .access import AccessPolicy
from .markdown import NO_MENTIONS, escape_text


LOGGER = logging.getLogger(__name__)
MAX_VISIBLE_TASKS = 5


@dataclass(frozen=True)
class DiscordTasksState:
    message_id: int = 0


class DiscordTasksSurface:
    def __init__(
        self,
        bot: discord.Client,
        policy: AccessPolicy,
        *,
        channel_id: int,
        profile: str,
        state_path: Path,
        adapter: CalendarAdapterClient,
    ) -> None:
        self.bot = bot
        self.policy = policy
        self.channel_id = channel_id
        self.profile = profile
        self.state_path = state_path
        self.adapter = adapter
        self.state = self._load_state()
        self._tasks_by_key: dict[str, dict[str, Any]] = {}

    async def ensure_message(self) -> None:
        tasks = await asyncio.to_thread(self.adapter.list_tasks, self.profile)
        active = active_tasks(tasks)
        self._tasks_by_key = {task_key(item): item for item in active}
        channel = await self.channel()
        content = render_active_tasks(active)
        view = TasksView(self, active)
        message = await self._upsert_message(channel, content=content, view=view)
        self.state = DiscordTasksState(message_id=int(message.id))
        self._save_state()

    async def handle_message(self, message: discord.Message) -> bool:
        if message.channel.id != self.channel_id:
            return False
        if message.author.bot:
            return self._is_own_message(message)
        await self._delete_message(message)
        return True

    async def complete_task(self, key: str) -> bool:
        task = self._tasks_by_key.get(key)
        if task is None:
            return False
        payload = task_payload(task, status="COMPLETED")
        await asyncio.to_thread(self.adapter.update_task, self.profile, payload)
        await self.ensure_message()
        return True

    async def delete_task(self, key: str) -> bool:
        task = self._tasks_by_key.get(key)
        if task is None:
            return False
        await asyncio.to_thread(
            self.adapter.delete_task,
            self.profile,
            str(task.get("uid") or ""),
            str(task.get("collection") or ""),
        )
        await self.ensure_message()
        return True

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "profile": self.profile,
            "messageId": str(self.state.message_id) if self.state.message_id else "",
        }

    async def channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not hasattr(channel, "send"):
            raise RuntimeError("tasks_channel_not_messageable")
        return channel

    async def _upsert_message(
        self,
        channel: discord.abc.Messageable,
        *,
        content: str,
        view: discord.ui.View,
    ) -> discord.Message:
        if self.state.message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(self.state.message_id)
                return await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("Tasks message %s missing; recreating", self.state.message_id)
        return await channel.send(content=content, view=view, allowed_mentions=NO_MENTIONS)

    def _load_state(self) -> DiscordTasksState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DiscordTasksState()
        try:
            return DiscordTasksState(
                message_id=int(raw.get("messageId") or 0),
            )
        except (TypeError, ValueError):
            return DiscordTasksState()

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "messageId": self.state.message_id,
        }
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o660)
        temporary.replace(self.state_path)

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete tasks channel message %s", getattr(message, "id", ""))

    def _is_own_message(self, message: discord.Message) -> bool:
        user = getattr(self.bot, "user", None)
        return user is not None and int(getattr(message.author, "id", 0)) == int(getattr(user, "id", 0))


class TasksView(discord.ui.View):
    def __init__(self, surface: DiscordTasksSurface, tasks: list[Mapping[str, Any]]) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        for index, task in enumerate(tasks[:MAX_VISIBLE_TASKS]):
            key = task_key(task)
            done = discord.ui.Button(
                label="Done",
                style=discord.ButtonStyle.success,
                custom_id=f"tasks:done:{index}",
                row=index,
            )
            edit = discord.ui.Button(
                label="Edit",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tasks:edit:{index}",
                row=index,
                disabled=True,
            )
            delete = discord.ui.Button(
                label="Delete",
                style=discord.ButtonStyle.danger,
                custom_id=f"tasks:delete:{index}",
                row=index,
            )
            done.callback = self._complete_callback(key)
            delete.callback = self._delete_callback(key)
            self.add_item(done)
            self.add_item(edit)
            self.add_item(delete)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.surface.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def _complete_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            if not await self.surface.complete_task(key):
                await interaction.followup.send("Task is no longer active.", ephemeral=True, allowed_mentions=NO_MENTIONS)

        return callback

    def _delete_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            if not await self.surface.delete_task(key):
                await interaction.followup.send("Task is no longer active.", ephemeral=True, allowed_mentions=NO_MENTIONS)

        return callback


def active_tasks(tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    active = [
        dict(item)
        for item in tasks
        if str(item.get("status") or "").upper() != "COMPLETED" and str(item.get("uid") or "")
    ]
    return sorted(active, key=lambda item: (str(item.get("due") or "9999-12-31"), str(item.get("summary") or ""), str(item.get("uid") or "")))[:MAX_VISIBLE_TASKS]


def render_active_tasks(tasks: list[Mapping[str, Any]]) -> str:
    lines = ["## Active Tasks"]
    if not tasks:
        lines.append("-# No active tasks")
        return "\n".join(lines)
    for task in tasks:
        due = str(task.get("due") or "No due date")
        title = escape_text(task.get("summary") or "Untitled task")
        lines.append(f"### {title}")
        lines.append(f"- due: {escape_text(due)}")
    return "\n".join(lines)[:1990]


def task_payload(task: Mapping[str, Any], *, status: str) -> dict[str, Any]:
    due = str(task.get("due") or "")
    return {
        "uid": str(task.get("uid") or ""),
        "collectionId": str(task.get("collection") or ""),
        "title": str(task.get("summary") or "Untitled task"),
        "memo": str(task.get("description") or ""),
        "dueDate": due,
        "dueTime": str(task.get("dueTime") or ""),
        "priority": str(task.get("priority") or ""),
        "status": status,
    }


def task_key(task: Mapping[str, Any]) -> str:
    return f"{task.get('collection') or ''}|{task.get('uid') or ''}"
