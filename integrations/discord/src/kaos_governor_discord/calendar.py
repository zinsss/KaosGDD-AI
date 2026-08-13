from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import io
import json
import logging
import calendar as calendar_lib
from pathlib import Path
from typing import Any, Mapping

import discord
from kaos_governor.calendar import (
    CalendarAdapterClient,
    CalendarViewState,
    MonthDayMarkers,
    apply_calendar_command,
    parse_calendar_command,
    render_month_png,
    reset_idle_state,
)

from .access import AccessPolicy
from .markdown import NO_MENTIONS, escape_text


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscordCalendarState:
    view: CalendarViewState
    month_message_id: int = 0
    agenda_message_id: int = 0


class DiscordCalendarSurface:
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
        self.state = self._load_state(date.today())

    async def ensure_messages(self, *, today: date | None = None) -> None:
        current = today or date.today()
        if self.state.view.visible_year < 1:
            self.state = DiscordCalendarState(reset_idle_state(today=current))
        bootstrap = await asyncio.to_thread(self.adapter.bootstrap, self.profile)
        channel = await self.channel()
        month_content, month_file = await asyncio.to_thread(self._month_payload, bootstrap, current)
        agenda_content = await asyncio.to_thread(self._agenda_content, bootstrap, current)
        month_message = await self._upsert_message(
            channel,
            self.state.month_message_id,
            content=month_content,
            file=month_file,
            view=CalendarNavigationView(self),
        )
        agenda_message = await self._upsert_message(
            channel,
            self.state.agenda_message_id,
            content=agenda_content,
        )
        self.state = DiscordCalendarState(
            self.state.view,
            month_message_id=int(month_message.id),
            agenda_message_id=int(agenda_message.id),
        )
        self._save_state()

    async def handle_message(self, message: discord.Message, *, today: date | None = None) -> bool:
        if message.channel.id != self.channel_id:
            return False
        persistent_ids = {self.state.month_message_id, self.state.agenda_message_id}
        if message.author.bot:
            if self._is_own_message(message):
                return True
            if int(message.id) not in persistent_ids:
                await self._delete_message(message)
                return True
            return False
        if not self.policy.allows(message.guild.id if message.guild else None, message.channel.id, message.author.id):
            await self._delete_message(message)
            return True
        current = today or date.today()
        command = parse_calendar_command(message.content, state=self.state.view, today=current)
        if command.kind != "invalid":
            self.state = DiscordCalendarState(
                apply_calendar_command(self.state.view, command),
                month_message_id=self.state.month_message_id,
                agenda_message_id=self.state.agenda_message_id,
            )
            await self.ensure_messages(today=current)
        await self._delete_message(message)
        return True

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "profile": self.profile,
            "visibleYear": self.state.view.visible_year,
            "visibleMonth": self.state.view.visible_month,
            "agendaMode": self.state.view.agenda_mode,
            "agendaDate": self.state.view.agenda_date.isoformat() if self.state.view.agenda_date else "",
            "monthMessageId": str(self.state.month_message_id) if self.state.month_message_id else "",
            "agendaMessageId": str(self.state.agenda_message_id) if self.state.agenda_message_id else "",
        }

    async def channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not hasattr(channel, "send"):
            raise RuntimeError("calendar_channel_not_messageable")
        return channel

    async def _upsert_message(
        self,
        channel: discord.abc.Messageable,
        message_id: int,
        *,
        content: str,
        file: discord.File | None = None,
        view: discord.ui.View | None = None,
    ) -> discord.Message:
        if message_id and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(message_id)
                if file is None:
                    return await message.edit(content=content, view=view, allowed_mentions=NO_MENTIONS)
                return await message.edit(
                    content=content,
                    attachments=[file],
                    view=view,
                    allowed_mentions=NO_MENTIONS,
                )
            except (discord.NotFound, discord.HTTPException):
                LOGGER.info("Calendar message %s missing; recreating", message_id)
        kwargs: dict[str, Any] = {"content": content, "view": view, "allowed_mentions": NO_MENTIONS}
        if file is not None:
            kwargs["file"] = file
        return await channel.send(**kwargs)

    async def navigate_month(self, action: str, *, today: date | None = None) -> None:
        current = today or date.today()
        if action == "today":
            view = reset_idle_state(today=current)
        elif action in {"previous", "next"}:
            step = -1 if action == "previous" else 1
            year, month = add_months(self.state.view.visible_year, self.state.view.visible_month, step)
            view = CalendarViewState(year, month)
        else:
            return
        self.state = DiscordCalendarState(
            view,
            month_message_id=self.state.month_message_id,
            agenda_message_id=self.state.agenda_message_id,
        )
        await self.ensure_messages(today=current)

    def _month_payload(self, bootstrap: Mapping[str, Any], today: date) -> tuple[str, discord.File]:
        content = f"Calendar · {self.state.view.visible_year}.{self.state.view.visible_month:02d}"
        png = render_month_png(
            year=self.state.view.visible_year,
            month=self.state.view.visible_month,
            today=today,
            markers=month_markers(bootstrap),
        )
        filename = f"calendar-{self.state.view.visible_year}-{self.state.view.visible_month:02d}.png"
        return content, discord.File(io.BytesIO(png), filename=filename)

    def _agenda_content(self, bootstrap: Mapping[str, Any], today: date) -> str:
        if self.state.view.agenda_mode == "day" and self.state.view.agenda_date is not None:
            days = [self.state.view.agenda_date]
            title = f"Agenda · {self.state.view.agenda_date:%Y.%m.%d}"
        else:
            days = [today + timedelta(days=offset) for offset in range(7)]
            title = "Agenda · Upcoming 7 Days"
        return render_agenda(bootstrap, days=days, title=title)

    def _load_state(self, today: date) -> DiscordCalendarState:
        fallback = DiscordCalendarState(reset_idle_state(today=today))
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback
        try:
            agenda_date = date.fromisoformat(raw["agendaDate"]) if raw.get("agendaDate") else None
            return DiscordCalendarState(
                CalendarViewState(
                    visible_year=int(raw.get("visibleYear") or today.year),
                    visible_month=int(raw.get("visibleMonth") or today.month),
                    agenda_mode="day" if raw.get("agendaMode") == "day" else "upcoming",
                    agenda_date=agenda_date,
                ),
                month_message_id=int(raw.get("monthMessageId") or 0),
                agenda_message_id=int(raw.get("agendaMessageId") or 0),
            )
        except (TypeError, ValueError):
            return fallback

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "visibleYear": self.state.view.visible_year,
            "visibleMonth": self.state.view.visible_month,
            "agendaMode": self.state.view.agenda_mode,
            "agendaDate": self.state.view.agenda_date.isoformat() if self.state.view.agenda_date else "",
            "monthMessageId": self.state.month_message_id,
            "agendaMessageId": self.state.agenda_message_id,
        }
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o660)
        temporary.replace(self.state_path)

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete calendar channel message %s", getattr(message, "id", ""))

    def _is_own_message(self, message: discord.Message) -> bool:
        user = getattr(self.bot, "user", None)
        return user is not None and int(getattr(message.author, "id", 0)) == int(getattr(user, "id", 0))


class CalendarNavigationView(discord.ui.View):
    def __init__(self, surface: DiscordCalendarSurface) -> None:
        super().__init__(timeout=None)
        self.surface = surface

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.surface.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        if interaction.response.is_done():
            await interaction.followup.send("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary, custom_id="calendar:month:previous")
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._navigate(interaction, "previous")

    @discord.ui.button(label="Today", style=discord.ButtonStyle.primary, custom_id="calendar:month:today")
    async def today(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._navigate(interaction, "today")

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary, custom_id="calendar:month:next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._navigate(interaction, "next")

    async def _navigate(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.defer()
        await self.surface.navigate_month(action)


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    first = date(year, month, 1)
    ordinal = first.year * 12 + first.month - 1 + delta
    target_year, target_month_index = divmod(ordinal, 12)
    target_month = target_month_index + 1
    calendar_lib.monthrange(target_year, target_month)
    return target_year, target_month


def month_markers(bootstrap: Mapping[str, Any]) -> list[MonthDayMarkers]:
    collections = _collections_by_id(bootstrap)
    values: dict[date, dict[str, Any]] = defaultdict(
        lambda: {
            "public_holiday": False,
            "duty": False,
            "weather": "",
            "market_day": False,
            "family_events": 0,
            "zin_events": 0,
            "tasks": 0,
        }
    )
    for event in _items(bootstrap, "events"):
        value = _item_date(event, "startDate")
        if value is None:
            continue
        categories = {str(item).upper() for item in event.get("categories", [])}
        current = values[value]
        current["public_holiday"] = bool(current["public_holiday"] or event.get("publicHoliday"))
        current["duty"] = bool(current["duty"] or "당직" in str(event.get("summary") or ""))
        if "KAOS-MARKET-DAY" in categories:
            current["market_day"] = True
            continue
        if event.get("publicHoliday"):
            continue
        owner = collections.get(str(event.get("collection") or ""), {}).get("owner")
        if owner == "family":
            current["family_events"] += 1
        elif owner == "zin":
            current["zin_events"] += 1
    for task in _items(bootstrap, "tasks"):
        value = _item_date(task, "due")
        if value is None or str(task.get("status") or "").upper() == "COMPLETED":
            continue
        values[value]["tasks"] += 1
    return [
        MonthDayMarkers(
            value=value,
            public_holiday=bool(item["public_holiday"]),
            duty=bool(item["duty"]),
            weather=str(item["weather"]),
            market_day=bool(item["market_day"]),
            family_events=int(item["family_events"]),
            zin_events=int(item["zin_events"]),
            tasks=int(item["tasks"]),
        )
        for value, item in sorted(values.items())
    ]


def render_agenda(bootstrap: Mapping[str, Any], *, days: list[date], title: str) -> str:
    collections = _collections_by_id(bootstrap)
    events_by_day: dict[date, list[str]] = defaultdict(list)
    wanted = set(days)
    for event in _items(bootstrap, "events"):
        value = _item_date(event, "startDate")
        if value not in wanted:
            continue
        collection = collections.get(str(event.get("collection") or ""), {})
        time_value = str(event.get("startTime") or "")
        prefix = f"{time_value} " if time_value else ""
        suffix = agenda_owner_suffix(collection)
        events_by_day[value].append(f"- {prefix}{escape_text(event.get('summary') or 'Untitled event')}{suffix}")

    lines = [f"# {escape_text(title)}"]
    for value in days:
        day_lines = []
        if events_by_day[value]:
            day_lines.extend(events_by_day[value][:8])
        if not day_lines:
            continue
        if len(lines) > 1:
            lines.append("")
        lines.append(f"## {value:%Y.%m.%d %a}")
        lines.extend(day_lines)
    content = "\n".join(lines)
    return content[:1990]


def _collections_by_id(bootstrap: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("id") or ""): item
        for item in _items(bootstrap, "collections")
        if str(item.get("id") or "")
    }


def agenda_owner_suffix(collection: Mapping[str, Any]) -> str:
    if str(collection.get("owner") or "").lower() != "zin":
        return ""
    label = escape_text(collection.get("ownerLabel") or "GDD_ZiN")
    return f" · ***{label}***"


def _items(bootstrap: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    return [item for item in bootstrap.get(name, []) if isinstance(item, Mapping)]


def _item_date(item: Mapping[str, Any], key: str) -> date | None:
    try:
        raw = str(item.get(key) or "")
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None
