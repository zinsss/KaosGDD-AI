from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import discord

from .config import Settings
from .discord_formatting import (
    CALENDAR_TITLE,
    KST,
    _active_control_month_file_for,
    _render_calendar_weekly,
    _shift_month,
    _week_start_sunday,
)
from .discord_view_helpers import NO_MENTIONS
from .governor_tools import GovernorToolClient


class BrainCalendarMonthView(discord.ui.View):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        settings: Settings,
        *,
        anchor_date: date,
        year: int,
        month: int,
        mode: str = "month",
    ) -> None:
        super().__init__(timeout=None)
        self.governor_tools = governor_tools
        self.settings = settings
        self.anchor_date = anchor_date
        self.year = year
        self.month = month
        self.mode = mode

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild_id == self.settings.guild_id
            and interaction.channel_id == self.settings.brain_channel_id
            and int(interaction.user.id) in self.settings.allowed_user_ids
        ):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def content(self) -> str:
        return f"## {CALENDAR_TITLE} · {self.year}.{self.month:02d}"

    async def weekly_content(self) -> str:
        return await _render_calendar_weekly(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            start=_week_start_sunday(self.anchor_date),
        )

    async def month_file(self) -> discord.File | None:
        return await _active_control_month_file_for(
            self.governor_tools,
            profile=self.settings.governor_tools_profile,
            year=self.year,
            month=self.month,
            today=datetime.now(KST).date(),
        )

    async def _edit_current(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if self.mode == "weekly":
            kwargs: dict[str, Any] = {
                "content": await self.weekly_content(),
                "view": self,
                "attachments": [],
                "allowed_mentions": NO_MENTIONS,
            }
        else:
            file = await self.month_file()
            kwargs = {
                "content": self.content(),
                "view": self,
                "allowed_mentions": NO_MENTIONS,
            }
            if file is not None:
                kwargs["attachments"] = [file]
        await interaction.edit_original_response(**kwargs)

    @discord.ui.button(label="Month", style=discord.ButtonStyle.secondary, row=0)
    async def month_view(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.mode = "month"
        await self._edit_current(interaction)

    @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, row=0)
    async def weekly_view(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.mode = "weekly"
        await self._edit_current(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, row=0)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary, row=1)
    async def previous_month(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.mode == "weekly":
            self.anchor_date -= timedelta(days=7)
        else:
            self.year, self.month = _shift_month(self.year, self.month, -1)
        await self._edit_current(interaction)

    @discord.ui.button(label="Today", style=discord.ButtonStyle.primary, row=1)
    async def today_month(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        current = datetime.now(KST).date()
        self.anchor_date = current
        self.year = current.year
        self.month = current.month
        await self._edit_current(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary, row=1)
    async def next_month(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.mode == "weekly":
            self.anchor_date += timedelta(days=7)
        else:
            self.year, self.month = _shift_month(self.year, self.month, 1)
        await self._edit_current(interaction)
