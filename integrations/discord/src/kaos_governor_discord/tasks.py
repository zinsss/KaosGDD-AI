from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Mapping

import discord
from kaos_governor.calendar import CalendarAdapterClient

from .access import AccessPolicy
from .markdown import NO_MENTIONS, escape_text


LOGGER = logging.getLogger(__name__)
MAX_VISIBLE_TASKS = 25
MAX_RECENT_SUPPLIES = 25
TASK_PRIORITIES = {"", "1", "5", "9"}
DUE_LINE_PATTERN = re.compile(r"^:(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?$")
MESSAGE_REFRESH_DELAY_SECONDS = 0.35
KST = timezone(timedelta(hours=9))


@dataclass
class DiscordTasksState:
    message_ids: dict[str, int] = field(default_factory=dict)
    completed_message_ids: dict[str, list[int]] = field(default_factory=dict)
    completed_archive_message_id: int = 0
    recent_supplies_message_id: int = 0
    recent_supplies: list[str] = field(default_factory=list)
    due_notification_keys: set[str] = field(default_factory=set)
    legacy_message_id: int = 0


@dataclass(frozen=True)
class AddTaskCommand:
    title: str
    due_date: str = ""
    due_time: str = ""


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
        surface_name: str = "tasks",
        button_prefix: str = "tasks",
        collection_id: str = "",
        show_due: bool = True,
    ) -> None:
        self.bot = bot
        self.policy = policy
        self.channel_id = channel_id
        self.profile = profile
        self.state_path = state_path
        self.adapter = adapter
        self.surface_name = surface_name
        self.button_prefix = button_prefix
        self.collection_id = collection_id
        self.show_due = show_due
        self.message_refresh_delay_seconds = MESSAGE_REFRESH_DELAY_SECONDS
        self.state = self._load_state()
        self._tasks_by_key: dict[str, dict[str, Any]] = {}

    async def ensure_message(self) -> None:
        tasks = await asyncio.to_thread(self.adapter.list_tasks, self.profile)
        active = active_tasks(tasks, collection_id=self.collection_id)
        self._tasks_by_key = {task_key(item): item for item in active}
        channel = await self.channel()
        if self.state.legacy_message_id:
            await self._delete_message_id(channel, self.state.legacy_message_id)
            self.state.legacy_message_id = 0
        archive_message = await self._upsert_completed_archive_message(channel, tasks)
        self.state.completed_archive_message_id = int(archive_message.id)
        await self._pace_message_refresh()
        next_message_ids: dict[str, int] = {}
        previous_message_ids = dict(self.state.message_ids)
        tasks_by_key = {task_key(item): item for item in tasks if str(item.get("uid") or "")}
        message_order_changed = False
        for task in active:
            key = task_key(task)
            if await self._delete_completed_messages(key, channel):
                message_order_changed = True
                await self._pace_message_refresh()
            message_id = self.state.message_ids.get(key, 0)
            if not message_id:
                message_order_changed = True
            message = await self._upsert_task_message(
                channel,
                key,
                task,
                message_id=message_id,
            )
            next_message_ids[key] = int(message.id)
            await self._pace_message_refresh()
        for key, message_id in self.state.message_ids.items():
            if key not in next_message_ids:
                task = tasks_by_key.get(key)
                if task is not None and str(task.get("status") or "").upper() == "COMPLETED":
                    if await self._mark_message_completed(message_id, task):
                        self._record_completed_message(key, message_id)
                    else:
                        await self._delete_message_id(channel, message_id)
                    await self._pace_message_refresh()
                else:
                    await self._delete_message_id(channel, message_id)
                message_order_changed = True
        self.state.message_ids = next_message_ids
        if self._uses_supplies_rules():
            recent_supplies_was_empty = not self.state.recent_supplies
            for task in active:
                if recent_supplies_was_empty or task_key(task) not in previous_message_ids:
                    self._record_recent_supply(str(task.get("summary") or ""), promote_existing=False)
            recent_message = await self._recreate_recent_supplies_message(channel, force_recreate=message_order_changed)
            self.state.recent_supplies_message_id = int(recent_message.id)
            await self._pace_message_refresh()
        for key, message_ids in self.state.completed_message_ids.items():
            for message_id in message_ids:
                self._register_view(CompletedTaskMessageView(self, key), message_id)
        self._save_state()

    async def repost_active_messages(self) -> None:
        channel = await self.channel()
        for message_id in self.state.message_ids.values():
            await self._delete_message_id(channel, message_id)
        self.state.message_ids = {}
        self._save_state()
        await self.ensure_message()
        if await self._delete_all_completed_messages(channel):
            self._save_state()

    async def notify_due_tasks(self, *, now: datetime | None = None) -> int:
        if not self.show_due:
            return 0
        current = now or datetime.now(KST).replace(tzinfo=None)
        tasks = await asyncio.to_thread(self.adapter.list_tasks, self.profile)
        active = active_tasks(tasks, collection_id=self.collection_id)
        self._tasks_by_key.update({task_key(item): item for item in active})
        channel = await self.channel()
        sent = 0
        previous_keys = set(self.state.due_notification_keys)
        retained_keys = {
            key
            for key in self.state.due_notification_keys
            if key.split("|")[-1] >= current.date().isoformat()
        }
        self.state.due_notification_keys = retained_keys
        for task in active:
            due_at = due_notification_time(task)
            if due_at is None or due_at.date() != current.date():
                continue
            if current < due_at - timedelta(hours=1):
                continue
            notification_key = due_notification_key(task)
            if notification_key in self.state.due_notification_keys:
                continue
            key = task_key(task)
            await channel.send(
                content=render_due_notification_message(task),
                view=TaskView(self, key),
                allowed_mentions=NO_MENTIONS,
            )
            self.state.due_notification_keys.add(notification_key)
            sent += 1
            await self._pace_message_refresh()
        if sent or previous_keys != self.state.due_notification_keys:
            self._save_state()
        return sent

    async def handle_message(self, message: discord.Message) -> bool:
        if message.channel.id != self.channel_id:
            return False
        if message.author.bot:
            return self._is_own_message(message)
        command = parse_add_task_message(str(message.content or ""))
        if command is not None:
            await self.create_task(command)
        elif self._uses_supplies_rules():
            remembered_title = self._remembered_supply_title(str(message.content or ""))
            if remembered_title:
                channel = await self.channel()
                await channel.send(
                    content=render_remembered_supply_confirmation(remembered_title),
                    view=RememberedSupplyConfirmationView(self, remembered_title),
                    allowed_mentions=NO_MENTIONS,
                )
        await self._delete_message(message)
        return True

    async def create_task(self, command: AddTaskCommand | str) -> bool:
        if isinstance(command, AddTaskCommand):
            clean_title = command.title.strip()
            due_date = command.due_date
            due_time = command.due_time
        else:
            clean_title = command.strip()
            due_date = ""
            due_time = ""
        if not clean_title:
            return False
        payload = {
            "title": clean_title,
            "memo": "",
            "dueDate": due_date,
            "dueTime": due_time,
            "priority": "",
        }
        if self.collection_id:
            payload["collectionId"] = self.collection_id
        payload = normalize_supplies_due(payload, collection_id=self.collection_id)
        result = await asyncio.to_thread(self.adapter.create_task, self.profile, payload)
        uid = str(result.get("uid") or "")
        if not uid:
            return False
        if self._uses_supplies_rules():
            self._record_recent_supply(clean_title)
        await self.ensure_message()
        return True

    async def complete_task(self, key: str, *, notification_message_id: int = 0) -> bool:
        task = self._tasks_by_key.get(key)
        if task is None:
            return False
        payload = task_payload(task, status="COMPLETED")
        payload = normalize_supplies_due(payload, collection_id=self.collection_id or str(task.get("collection") or ""))
        await asyncio.to_thread(self.adapter.update_task, self.profile, payload)
        message_id = self.state.message_ids.pop(key, 0)
        self._tasks_by_key.pop(key, None)
        self._save_state()
        if message_id:
            if await self._mark_message_completed(message_id, {**task, "status": "COMPLETED"}):
                self._record_completed_message(key, message_id)
        if notification_message_id and notification_message_id != message_id:
            if await self._mark_message_completed(notification_message_id, {**task, "status": "COMPLETED"}):
                self._record_completed_message(key, notification_message_id)
        await self.ensure_message()
        return True

    async def reopen_completed_task(self, key: str) -> bool:
        task = await self._task_by_key(key)
        if task is None or str(task.get("status") or "").upper() != "COMPLETED":
            return False
        payload = task_payload(task, status="NEEDS-ACTION")
        payload = normalize_supplies_due(payload, collection_id=self.collection_id or str(task.get("collection") or ""))
        await asyncio.to_thread(self.adapter.update_task, self.profile, payload)
        await self.ensure_message()
        return True

    async def edit_task(
        self,
        key: str,
        *,
        title: str,
        memo: str,
        due_date: str = "",
        due_time: str = "",
        priority: str = "",
    ) -> tuple[bool, str]:
        task = await self._task_by_key(key)
        if task is None:
            return False, f"{self.surface_name}_not_active"
        clean_title = " ".join(title.strip().split())
        if not clean_title:
            return False, "title_required"
        clean_memo = memo.strip()
        clean_due_date = due_date.strip()
        clean_due_time = due_time.strip()
        clean_priority = priority.strip()
        if self._uses_supplies_rules():
            clean_due_date = ""
            clean_due_time = ""
            clean_priority = ""
        else:
            normalized_due = validate_edit_due(clean_due_date, clean_due_time)
            if normalized_due is None:
                return False, "invalid_due"
            clean_due_date, clean_due_time = normalized_due
            if clean_priority not in TASK_PRIORITIES:
                return False, "invalid_priority"
        payload = {
            "uid": str(task.get("uid") or ""),
            "collectionId": str(task.get("collection") or ""),
            "title": clean_title,
            "memo": clean_memo,
            "dueDate": clean_due_date,
            "dueTime": clean_due_time,
            "priority": clean_priority,
            "status": str(task.get("status") or "NEEDS-ACTION"),
        }
        payload = normalize_supplies_due(payload, collection_id=self.collection_id or str(task.get("collection") or ""))
        await asyncio.to_thread(self.adapter.update_task, self.profile, payload)
        if str(task.get("status") or "").upper() == "COMPLETED":
            updated_task = {
                **task,
                "summary": clean_title,
                "description": clean_memo,
                "due": clean_due_date,
                "dueTime": clean_due_time,
                "priority": clean_priority,
            }
            await self._refresh_completed_messages(key, updated_task)
        await self.ensure_message()
        return True, ""

    async def delete_task(self, key: str) -> bool:
        task = await self._task_by_key(key)
        if task is None:
            return False
        await asyncio.to_thread(
            self.adapter.delete_task,
            self.profile,
            str(task.get("uid") or ""),
            str(task.get("collection") or ""),
        )
        channel = await self.channel()
        await self._delete_completed_messages(key, channel)
        await self.ensure_message()
        return True

    async def _task_by_key(self, key: str) -> dict[str, Any] | None:
        task = self._tasks_by_key.get(key)
        if task is not None:
            return task
        tasks = await asyncio.to_thread(self.adapter.list_tasks, self.profile)
        for item in tasks:
            if task_key(item) == key:
                return dict(item)
        return None

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "profile": self.profile,
            "collectionId": self.collection_id,
            "messageCount": len(self.state.message_ids),
            "messageIds": [str(value) for value in self.state.message_ids.values()],
            "completedArchiveMessageId": str(self.state.completed_archive_message_id),
            "recentSuppliesMessageId": str(self.state.recent_supplies_message_id),
            "recentSuppliesCount": len(self.state.recent_supplies),
            "dueNotificationCount": len(self.state.due_notification_keys),
        }

    async def channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not hasattr(channel, "send"):
            raise RuntimeError(f"{self.surface_name}_channel_not_messageable")
        return channel

    async def _upsert_task_message(
        self,
        channel: discord.abc.Messageable,
        key: str,
        task: Mapping[str, Any],
        *,
        message_id: int,
    ) -> discord.Message:
        content = render_task_message(task, show_due=self.show_due)
        view = TaskView(self, key)
        if message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(message_id)
                if _message_matches(message, content=content, view=view):
                    self._register_view(view, int(message.id))
                    return message
                return await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("%s message %s missing; recreating", self.surface_name.capitalize(), message_id)
        return await channel.send(content=content, view=view, allowed_mentions=NO_MENTIONS)

    async def _upsert_completed_archive_message(
        self,
        channel: discord.abc.Messageable,
        tasks: list[Mapping[str, Any]],
    ) -> discord.Message:
        content = render_completed_archive_message(tasks, collection_id=self.collection_id)
        completed = completed_tasks_for_month(tasks, collection_id=self.collection_id)
        view = CompletedTasksView(self, completed) if completed else None
        message_id = self.state.completed_archive_message_id
        if message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(message_id)
                if _message_matches(message, content=content, view=view):
                    self._register_view(view, int(message.id))
                    return message
                return await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info(
                    "%s completed archive message %s missing; recreating",
                    self.surface_name.capitalize(),
                    message_id,
                )
        return await channel.send(content=content, view=view, allowed_mentions=NO_MENTIONS)

    async def _pace_message_refresh(self) -> None:
        if self.message_refresh_delay_seconds > 0:
            await asyncio.sleep(self.message_refresh_delay_seconds)

    def _load_state(self) -> DiscordTasksState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DiscordTasksState()
        try:
            message_ids = {
                str(key): int(value)
                for key, value in dict(raw.get("messageIds") or {}).items()
                if str(key) and int(value)
            }
            completed_message_ids = {
                str(key): [int(item) for item in list(value or []) if int(item)]
                for key, value in dict(raw.get("completedMessageIds") or {}).items()
                if str(key)
            }
            return DiscordTasksState(
                message_ids=message_ids,
                completed_message_ids=completed_message_ids,
                completed_archive_message_id=int(raw.get("completedArchiveMessageId") or 0),
                recent_supplies_message_id=int(raw.get("recentSuppliesMessageId") or 0),
                recent_supplies=[
                    str(item).strip()
                    for item in list(raw.get("recentSupplies") or [])
                    if str(item).strip()
                ][:MAX_RECENT_SUPPLIES],
                due_notification_keys={
                    str(item).strip()
                    for item in list(raw.get("dueNotificationKeys") or [])
                    if str(item).strip()
                },
                legacy_message_id=int(raw.get("messageId") or 0),
            )
        except (TypeError, ValueError):
            return DiscordTasksState()

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "messageIds": self.state.message_ids,
            "completedMessageIds": self.state.completed_message_ids,
            "completedArchiveMessageId": self.state.completed_archive_message_id,
            "recentSuppliesMessageId": self.state.recent_supplies_message_id,
            "recentSupplies": self.state.recent_supplies[:MAX_RECENT_SUPPLIES],
            "dueNotificationKeys": sorted(self.state.due_notification_keys),
        }
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o660)
        temporary.replace(self.state_path)

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete %s channel message %s", self.surface_name, getattr(message, "id", ""))

    async def _delete_message_id(self, channel: discord.abc.Messageable, message_id: int) -> None:
        if not message_id or not hasattr(channel, "fetch_message"):
            return
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except (discord.NotFound, discord.HTTPException):
            LOGGER.info("Could not delete stale %s message %s", self.surface_name, message_id)

    async def _delete_completed_messages(self, key: str, channel: discord.abc.Messageable) -> bool:
        message_ids = self.state.completed_message_ids.pop(key, [])
        deleted = False
        for message_id in message_ids:
            await self._delete_message_id(channel, message_id)
            deleted = True
        return deleted

    async def _delete_all_completed_messages(self, channel: discord.abc.Messageable) -> bool:
        if not self.state.completed_message_ids:
            return False
        message_ids = [
            message_id
            for task_message_ids in self.state.completed_message_ids.values()
            for message_id in task_message_ids
        ]
        self.state.completed_message_ids = {}
        for message_id in message_ids:
            await self._delete_message_id(channel, message_id)
        return bool(message_ids)

    async def _refresh_completed_messages(self, key: str, task: Mapping[str, Any]) -> None:
        message_ids = self.state.completed_message_ids.get(key, [])
        for message_id in message_ids:
            await self._mark_message_completed(message_id, {**task, "status": "COMPLETED"})

    def _record_completed_message(self, key: str, message_id: int) -> None:
        if not message_id:
            return
        message_ids = self.state.completed_message_ids.setdefault(key, [])
        if message_id not in message_ids:
            message_ids.append(message_id)

    async def _mark_message_completed(self, message_id: int, task: Mapping[str, Any]) -> bool:
        channel = await self.channel()
        if not hasattr(channel, "fetch_message"):
            return False
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(
                content=render_task_message(task, show_due=self.show_due, completed=True),
                view=CompletedTaskMessageView(self, task_key(task)),
                allowed_mentions=NO_MENTIONS,
            )
            self._register_view(CompletedTaskMessageView(self, task_key(task)), int(message.id))
            return True
        except (discord.NotFound, discord.HTTPException):
            LOGGER.info("Could not mark completed %s message %s", self.surface_name, message_id)
            return False

    def _is_own_message(self, message: discord.Message) -> bool:
        user = getattr(self.bot, "user", None)
        return user is not None and int(getattr(message.author, "id", 0)) == int(getattr(user, "id", 0))

    def _uses_supplies_rules(self) -> bool:
        return self.surface_name == "supplies" or self.profile == "supplies" or is_supplies_collection(self.collection_id)

    def _record_recent_supply(self, title: str, *, promote_existing: bool = True) -> bool:
        clean_title = title.strip()
        if not clean_title:
            return False
        if not promote_existing and any(item.casefold() == clean_title.casefold() for item in self.state.recent_supplies):
            return False
        previous = [item for item in self.state.recent_supplies if item.casefold() != clean_title.casefold()]
        self.state.recent_supplies = [clean_title, *previous][:MAX_RECENT_SUPPLIES]
        return True

    def _remembered_supply_title(self, content: str) -> str:
        clean_title = " ".join(str(content or "").split())
        if not clean_title or "\n" in str(content or "") or clean_title.startswith(("+", ":")):
            return ""
        for item in self.state.recent_supplies:
            if item.casefold() == clean_title.casefold():
                return item
        return ""

    async def _recreate_recent_supplies_message(
        self,
        channel: discord.abc.Messageable,
        *,
        force_recreate: bool = False,
    ) -> discord.Message:
        view = RecentSuppliesView(self, self.state.recent_supplies) if self.state.recent_supplies else None
        content = render_recent_supplies_message(self.state.recent_supplies)
        if self.state.recent_supplies_message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(self.state.recent_supplies_message_id)
                if force_recreate:
                    await message.delete()
                    self.state.recent_supplies_message_id = 0
                    return await channel.send(content=content, view=view, allowed_mentions=NO_MENTIONS)
                if _message_matches(message, content=content, view=view):
                    self._register_view(view, int(message.id))
                    return message
                return await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("%s recent supplies message %s missing; recreating", self.surface_name.capitalize(), self.state.recent_supplies_message_id)
                self.state.recent_supplies_message_id = 0
        return await channel.send(
            content=content,
            view=view,
            allowed_mentions=NO_MENTIONS,
        )

    def _register_view(self, view: discord.ui.View | None, message_id: int) -> None:
        if view is None or not hasattr(self.bot, "add_view"):
            return
        try:
            self.bot.add_view(view, message_id=message_id)
        except ValueError:
            LOGGER.info("Could not register persistent %s view for message %s", self.surface_name, message_id)


class TaskView(discord.ui.View):
    def __init__(self, surface: DiscordTasksSurface, key: str) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        done = discord.ui.Button(label="Done", style=discord.ButtonStyle.success, custom_id=f"{surface.button_prefix}:done")
        edit = discord.ui.Button(
            label="Edit",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{surface.button_prefix}:edit",
        )
        delete = discord.ui.Button(
            label="Delete",
            style=discord.ButtonStyle.danger,
            custom_id=f"{surface.button_prefix}:delete",
        )
        done.callback = self._complete_callback(key)
        edit.callback = self._edit_callback(key)
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
            notification_message_id = int(getattr(getattr(interaction, "message", None), "id", 0) or 0)
            if not await self.surface.complete_task(key, notification_message_id=notification_message_id):
                await interaction.followup.send(
                    f"{self.surface.surface_name.capitalize()} is no longer active.",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )

        return callback

    def _edit_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            task = self.surface._tasks_by_key.get(key)
            if task is None:
                await interaction.response.send_message(
                    f"{self.surface.surface_name.capitalize()} is no longer active.",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
                return
            await interaction.response.send_modal(TaskEditModal(self.surface, key, task))

        return callback

    def _delete_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            if not await self.surface.delete_task(key):
                await interaction.followup.send(
                    f"{self.surface.surface_name.capitalize()} is no longer active.",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )

        return callback


class CompletedTaskMessageView(discord.ui.View):
    def __init__(self, surface: DiscordTasksSurface, key: str) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        undone = discord.ui.Button(
            label="Undone",
            style=discord.ButtonStyle.success,
            custom_id=f"{surface.button_prefix}:completed:undone",
        )
        edit = discord.ui.Button(
            label="Edit",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{surface.button_prefix}:completed:edit",
        )
        delete = discord.ui.Button(
            label="Delete",
            style=discord.ButtonStyle.danger,
            custom_id=f"{surface.button_prefix}:completed:delete",
        )
        undone.callback = self._undone_callback(key)
        edit.callback = self._edit_callback(key)
        delete.callback = self._delete_callback(key)
        self.add_item(undone)
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

    def _undone_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            if not await self.surface.reopen_completed_task(key):
                await interaction.followup.send(
                    f"{self.surface.surface_name.capitalize()} is no longer completed.",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )

        return callback

    def _edit_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            task = await self.surface._task_by_key(key)
            if task is None:
                await interaction.response.send_message(
                    f"{self.surface.surface_name.capitalize()} is no longer available.",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
                return
            await interaction.response.send_modal(TaskEditModal(self.surface, key, task))

        return callback

    def _delete_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            if not await self.surface.delete_task(key):
                await interaction.followup.send(
                    f"{self.surface.surface_name.capitalize()} is no longer available.",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )

        return callback


class TaskEditModal(discord.ui.Modal):
    def __init__(self, surface: DiscordTasksSurface, key: str, task: Mapping[str, Any]) -> None:
        super().__init__(title="Edit 비품" if surface._uses_supplies_rules() else "Edit Task", timeout=600)
        self.surface = surface
        self.key = key
        self.title_input = discord.ui.TextInput(
            label="Title",
            style=discord.TextStyle.short,
            required=True,
            default=str(task.get("summary") or "")[:100],
            max_length=100,
            custom_id=f"{surface.button_prefix}:edit:title",
        )
        self.memo_input = discord.ui.TextInput(
            label="Memo",
            style=discord.TextStyle.paragraph,
            required=False,
            default=str(task.get("description") or "")[:1000],
            max_length=1000,
            custom_id=f"{surface.button_prefix}:edit:memo",
        )
        self.add_item(self.title_input)
        self.add_item(self.memo_input)
        if not surface._uses_supplies_rules():
            self.due_date_input = discord.ui.TextInput(
                label="Due date",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("due") or "")[:10],
                placeholder="yyyy-mm-dd",
                max_length=10,
                custom_id=f"{surface.button_prefix}:edit:due-date",
            )
            self.due_time_input = discord.ui.TextInput(
                label="Due time",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("dueTime") or "")[:5],
                placeholder="HH:MM",
                max_length=5,
                custom_id=f"{surface.button_prefix}:edit:due-time",
            )
            self.priority_input = discord.ui.TextInput(
                label="Priority",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("priority") or "")[:1],
                placeholder="blank, 1, 5, or 9",
                max_length=1,
                custom_id=f"{surface.button_prefix}:edit:priority",
            )
            self.add_item(self.due_date_input)
            self.add_item(self.due_time_input)
            self.add_item(self.priority_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        due_date = str(getattr(self, "due_date_input", SimpleTextInput()).value or "")
        due_time = str(getattr(self, "due_time_input", SimpleTextInput()).value or "")
        priority = str(getattr(self, "priority_input", SimpleTextInput()).value or "")
        ok, error = await self.surface.edit_task(
            self.key,
            title=str(self.title_input.value or ""),
            memo=str(self.memo_input.value or ""),
            due_date=due_date,
            due_time=due_time,
            priority=priority,
        )
        if not ok:
            await interaction.followup.send(error, ephemeral=True, allowed_mentions=NO_MENTIONS)


class SimpleTextInput:
    value = ""


class RecentSuppliesView(discord.ui.View):
    def __init__(self, surface: DiscordTasksSurface, items: list[str]) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        self.items = items[:MAX_RECENT_SUPPLIES]
        for index, item in enumerate(self.items):
            button = discord.ui.Button(
                label=_button_label(item),
                style=discord.ButtonStyle.secondary,
                custom_id=f"{surface.button_prefix}:recent:add:{index}",
                row=index // 5,
            )
            button.callback = self._button_callback(index)
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.surface.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def _button_callback(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            try:
                title = self.items[index]
            except IndexError:
                return
            await self.surface.create_task(title)

        return callback


class RememberedSupplyConfirmationView(discord.ui.View):
    def __init__(self, surface: DiscordTasksSurface, title: str) -> None:
        super().__init__(timeout=300)
        self.surface = surface
        self.title = title
        add = discord.ui.Button(label="Add", style=discord.ButtonStyle.success)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        add.callback = self._add_callback()
        cancel.callback = self._cancel_callback()
        self.add_item(add)
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.surface.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def _add_callback(self):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            ok = await self.surface.create_task(self.title)
            if not ok:
                await interaction.followup.send("비품을 추가하지 못했어요.", ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            await _delete_interaction_message(interaction)

        return callback

    def _cancel_callback(self):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            await _delete_interaction_message(interaction)

        return callback


class CompletedTasksView(discord.ui.View):
    def __init__(self, surface: DiscordTasksSurface, tasks: list[Mapping[str, Any]]) -> None:
        super().__init__(timeout=None)
        self.surface = surface
        self.tasks = [dict(item) for item in tasks[:MAX_VISIBLE_TASKS]]
        select = discord.ui.Select(
            placeholder="완료 항목 선택",
            min_values=1,
            max_values=1,
            custom_id=f"{surface.button_prefix}:completed:select",
            options=[
                discord.SelectOption(label=_select_option_label(item.get("summary") or "Untitled task"), value=str(index))
                for index, item in enumerate(self.tasks)
            ],
        )
        select.callback = self._select_callback(select)
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.surface.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def _select_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            raw_value = select.values[0] if select.values else ""
            try:
                task = self.tasks[int(raw_value)]
            except (IndexError, ValueError):
                return
            title = escape_text(task.get("summary") or "Untitled task")
            await interaction.followup.send(
                f"## {title}",
                view=CompletedHistoryActionView(self.surface, task),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )

        return callback


class CompletedHistoryActionView(discord.ui.View):
    def __init__(self, surface: DiscordTasksSurface, task: Mapping[str, Any]) -> None:
        super().__init__(timeout=300)
        self.surface = surface
        self.task = dict(task)
        undone = discord.ui.Button(label="Undone", style=discord.ButtonStyle.success)
        make_new = discord.ui.Button(label="Make as new", style=discord.ButtonStyle.secondary)
        undone.callback = self._undone_callback()
        make_new.callback = self._make_new_callback()
        self.add_item(undone)
        self.add_item(make_new)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.surface.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def _undone_callback(self):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            key = task_key(self.task)
            if not await self.surface.reopen_completed_task(key):
                await interaction.followup.send(
                    f"{self.surface.surface_name.capitalize()} is no longer completed.",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )

        return callback

    def _make_new_callback(self):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            await self.surface.create_task(
                AddTaskCommand(
                    title=str(self.task.get("summary") or "Untitled task"),
                    due_date=str(self.task.get("due") or ""),
                    due_time=str(self.task.get("dueTime") or ""),
                )
            )

        return callback


def active_tasks(tasks: list[Mapping[str, Any]], *, collection_id: str = "") -> list[dict[str, Any]]:
    active = [
        dict(item)
        for item in tasks
        if str(item.get("status") or "").upper() != "COMPLETED" and str(item.get("uid") or "")
        and (not collection_id or str(item.get("collection") or "") == collection_id)
    ]
    return sorted(active, key=lambda item: (str(item.get("due") or "9999-12-31"), str(item.get("summary") or ""), str(item.get("uid") or "")))[:MAX_VISIBLE_TASKS]


def completed_tasks_for_month(
    tasks: list[Mapping[str, Any]],
    *,
    collection_id: str = "",
    month: date | None = None,
) -> list[dict[str, Any]]:
    current = month or date.today()
    completed = [
        dict(item)
        for item in tasks
        if str(item.get("status") or "").upper() == "COMPLETED"
        and str(item.get("uid") or "")
        and (not collection_id or str(item.get("collection") or "") == collection_id)
        and _task_month_date(item) is not None
        and _task_month_date(item).year == current.year
        and _task_month_date(item).month == current.month
    ]
    completed.sort(key=lambda item: (str(item.get("summary") or ""), str(item.get("uid") or "")))
    completed.sort(key=lambda item: _task_month_date(item) or date.min, reverse=True)
    return completed[:MAX_VISIBLE_TASKS]


def render_completed_archive_message(
    tasks: list[Mapping[str, Any]],
    *,
    collection_id: str = "",
    month: date | None = None,
) -> str:
    current = month or date.today()
    completed = completed_tasks_for_month(tasks, collection_id=collection_id, month=current)
    lines = [f"## Completed · {current:%Y.%m}"]
    if not completed:
        lines.append("- none")
    else:
        show_date = not _collection_is_supplies(collection_id)
        lines.extend(_completed_archive_line(item, show_date=show_date) for item in completed)
    return "\n".join(lines)[:1990]


def render_recent_supplies_message(items: list[str]) -> str:
    lines = ["## 최근 비품"]
    if not items:
        lines.append("- none")
    return "\n".join(lines)[:1990]


def render_remembered_supply_confirmation(title: str) -> str:
    return f"## 비품 다시 추가\n- {escape_text(title)}"


def parse_add_task_message(content: str) -> AddTaskCommand | None:
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    if not lines or not lines[0].startswith("+"):
        return None
    title = lines[0][1:].strip()
    if not title:
        return None
    if len(lines) == 1:
        return AddTaskCommand(title=title)
    if len(lines) != 2 or not lines[1].startswith(":"):
        return None
    due = parse_due_line(lines[1])
    if due is None:
        return None
    due_date, due_time = due
    return AddTaskCommand(title=title, due_date=due_date, due_time=due_time)


def parse_due_line(line: str) -> tuple[str, str] | None:
    match = DUE_LINE_PATTERN.fullmatch(line.strip())
    if match is None:
        return None
    due_date = match.group(1)
    due_time = match.group(2) or "10:00"
    try:
        datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return due_date, due_time


def validate_edit_due(due_date: str, due_time: str) -> tuple[str, str] | None:
    clean_due_date = due_date.strip()
    clean_due_time = due_time.strip()
    if not clean_due_date:
        return None if clean_due_time else ("", "")
    if clean_due_time:
        return parse_due_line(f":{clean_due_date} {clean_due_time}")
    return parse_due_line(f":{clean_due_date}")


def render_task_message(task: Mapping[str, Any], *, show_due: bool = True, completed: bool | None = None) -> str:
    due = str(task.get("due") or "")
    due_time = str(task.get("dueTime") or "")
    title = escape_text(task.get("summary") or "Untitled task")
    is_completed = str(task.get("status") or "").upper() == "COMPLETED" if completed is None else completed
    if is_completed:
        title = f"~~{title}~~"
    lines = [f"## {title}"]
    if show_due and due:
        due_text = escape_text(f"{due} {due_time}" if due_time else due)
        if is_completed:
            due_text = f"~~{due_text}~~"
        lines.append(f"- due: {due_text}")
    return "\n".join(lines)[:1990]


def render_due_notification_message(task: Mapping[str, Any]) -> str:
    due_at = due_notification_time(task)
    title = escape_text(task.get("summary") or "Untitled task")
    due_text = ""
    if due_at is not None:
        due_text = due_at.strftime("%Y-%m-%d %H:%M")
    return "\n".join(
        [
            "## Due task",
            f"### {title}",
            f"- due: {escape_text(due_text)}" if due_text else "- due: today",
        ]
    )[:1990]


def due_notification_time(task: Mapping[str, Any]) -> datetime | None:
    due = str(task.get("due") or "").strip()
    if not due:
        return None
    due_time = str(task.get("dueTime") or "10:00").strip() or "10:00"
    try:
        return datetime.strptime(f"{due[:10]} {due_time[:5]}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def due_notification_key(task: Mapping[str, Any]) -> str:
    due_at = due_notification_time(task)
    due_date = due_at.date().isoformat() if due_at is not None else str(task.get("due") or "")[:10]
    due_time = due_at.strftime("%H:%M") if due_at is not None else str(task.get("dueTime") or "")[:5]
    return f"{task_key(task)}|{due_date}T{due_time}|{due_date}"


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


def normalize_supplies_due(payload: dict[str, Any], *, collection_id: str = "") -> dict[str, Any]:
    resolved_collection_id = collection_id or str(payload.get("collectionId") or "")
    if is_supplies_collection(resolved_collection_id):
        payload = dict(payload)
        payload["dueDate"] = ""
        payload["dueTime"] = ""
    return payload


def is_supplies_collection(collection_id: str) -> bool:
    return "supplies" in collection_id.lower()


def _message_matches(message: discord.Message, *, content: str, view: discord.ui.View | None) -> bool:
    return str(getattr(message, "content", "") or "") == content and _message_view_signature(message) == _view_signature(view)


def _message_view_signature(message: discord.Message) -> tuple[tuple[str, str], ...]:
    view = getattr(message, "view", None)
    if view is not None:
        return _view_signature(view)
    signature: list[tuple[str, str]] = []
    for row in getattr(message, "components", []) or []:
        for item in getattr(row, "children", []) or []:
            signature.append((str(getattr(item, "custom_id", "") or ""), str(getattr(item, "label", "") or "")))
    return tuple(signature)


def _view_signature(view: discord.ui.View | None) -> tuple[tuple[str, str], ...]:
    if view is None:
        return ()
    return tuple(
        (
            str(getattr(item, "custom_id", "") or ""),
            str(getattr(item, "label", "") or ""),
        )
        for item in getattr(view, "children", [])
    )


async def _delete_interaction_message(interaction: discord.Interaction) -> None:
    message = getattr(interaction, "message", None)
    if message is None or not hasattr(message, "delete"):
        return
    try:
        await message.delete()
    except discord.HTTPException:
        LOGGER.info("Could not delete interaction message %s", getattr(message, "id", ""))


def task_key(task: Mapping[str, Any]) -> str:
    return f"{task.get('collection') or ''}|{task.get('uid') or ''}"


def _completed_archive_line(task: Mapping[str, Any], *, show_date: bool = True) -> str:
    completed = _task_month_date(task)
    date_text = _completed_archive_date_text(completed)
    title = escape_text(task.get("summary") or "Untitled task")
    scope = _completed_archive_scope_suffix(task)
    if not show_date:
        return f"- {title}{scope}"
    return f"- {date_text} - {title}{scope}"


def _completed_archive_date_text(value: date | None) -> str:
    if value is None:
        return "unknown"
    weekdays = ("월", "화", "수", "목", "금", "토", "일")
    return f"{value.day:02d}.{weekdays[value.weekday()]}"


def _completed_archive_scope_suffix(task: Mapping[str, Any]) -> str:
    collection = str(task.get("collection") or "")
    if collection.startswith("family:"):
        return " **<family>**"
    return ""


def _collection_is_supplies(collection_id: str) -> bool:
    return "supplies" in collection_id.lower()


def _task_month_date(task: Mapping[str, Any]) -> date | None:
    for key in ("completed", "completedAt", "completedDate", "lastModified", "updated", "due"):
        raw = str(task.get(key) or "").strip()
        if not raw:
            continue
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            continue
    return None


def _select_option_label(value: str) -> str:
    label = value.strip() or "Untitled"
    return label[:100]


def _button_label(value: str) -> str:
    label = value.strip() or "Untitled"
    return label[:80]
