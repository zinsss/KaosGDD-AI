from __future__ import annotations

import logging
from typing import Any

import discord

from .config import Settings
from .discord_formatting import (
    FAX_MAIL_PAGE_SIZE,
    _fax_mail_mode_label,
    _fax_mail_option_description,
    _fax_mail_option_label,
    _fax_mail_results,
    _mail_message_results,
    _render_fax_mail_selection,
    _render_fax_mail_service_message,
)
from .discord_view_helpers import NO_MENTIONS, BrainServiceMessageView, _inherit_bound_view_state
from .governor_tools import GovernorToolClient, GovernorToolError
from .list_formatting import page_status_label
from .tool_intent import ToolKind, ToolRequest

LOGGER = logging.getLogger(__name__)


def _tool_failed(action: str) -> str:
    return f"{action} 실패했어요."


class BrainFaxMailView(BrainServiceMessageView):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        settings: Settings,
        items: list[dict[str, Any]],
        *,
        mode: str = "incoming_fax",
        page: int = 0,
    ) -> None:
        super().__init__()
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.settings = settings
        self.items = items
        self.mode = {"incoming": "incoming_fax", "outgoing": "outgoing_fax"}.get(mode, mode)
        if self.mode not in {"incoming_fax", "outgoing_fax", "mail"}:
            self.mode = "incoming_fax"
        self.page = max(0, page)
        self._rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @property
    def page_items(self) -> list[dict[str, Any]]:
        start = self.page * FAX_MAIL_PAGE_SIZE
        return self.items[start : start + FAX_MAIL_PAGE_SIZE]

    @property
    def max_page(self) -> int:
        if not self.items:
            return 0
        return (len(self.items) - 1) // FAX_MAIL_PAGE_SIZE

    def content(self) -> str:
        return _render_fax_mail_service_message(self.items, mode=self.mode, page=self.page)

    def _rebuild_items(self) -> None:
        self.clear_items()
        if self.page > self.max_page:
            self.page = self.max_page
        if self.page_items:
            self.add_item(BrainFaxMailSelect(self))
        self.add_item(BrainFaxMailPageButton("←", -1, disabled=self.page <= 0))
        self.add_item(BrainFaxMailPageStatusButton(self.page, self.max_page))
        self.add_item(BrainFaxMailPageButton("→", 1, disabled=self.page >= self.max_page))
        self.add_item(BrainFaxMailModeButton("Incoming Fax", "incoming_fax", active=self.mode == "incoming_fax"))
        self.add_item(BrainFaxMailModeButton("Outgoing Fax", "outgoing_fax", active=self.mode == "outgoing_fax"))
        self.add_item(BrainFaxMailModeButton("Mail", "mail", active=self.mode == "mail"))
        self.add_item(BrainFaxMailCloseButton())

    async def edit_message(self, interaction: discord.Interaction) -> None:
        self._rebuild_items()
        await interaction.edit_original_response(content=self.content(), view=self)

    async def refresh(self, *, mode: str, page: int = 0) -> "BrainFaxMailView":
        if mode == "mail":
            payload = await self.governor_tools.mail_messages(limit=50)
            items = _mail_message_results(payload)
        else:
            payload = await self.governor_tools.fetch(
                ToolRequest(ToolKind.RECENT_IMPORTS, profile=self.settings.governor_tools_profile)
            )
            items = _fax_mail_results(payload, mode="outgoing" if mode == "outgoing_fax" else "incoming")
        return BrainFaxMailView(
            self.governor_tools,
            self.actor_id,
            self.settings,
            items,
            mode=mode,
            page=page,
        )


class BrainFaxMailSelect(discord.ui.Select):
    def __init__(self, parent: BrainFaxMailView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=_fax_mail_option_label(item),
                description=_fax_mail_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.page_items)
        ]
        start = parent.page * FAX_MAIL_PAGE_SIZE + 1
        end = start + len(parent.page_items) - 1
        label = _fax_mail_mode_label(parent.mode)
        super().__init__(placeholder=f"{label} {start}-{end}", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.page_items[int(self.values[0])]
        except (IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Fax Mail selection failed: %s", exc)
            await interaction.response.send_message(_tool_failed("Fax Mail 선택"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.send_message(_render_fax_mail_selection(item), ephemeral=True, allowed_mentions=NO_MENTIONS)


class BrainFaxMailPageButton(discord.ui.Button):
    def __init__(self, label: str, delta: int, *, disabled: bool = False) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1, disabled=disabled)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, BrainFaxMailView):
            await interaction.response.send_message("View unavailable.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        view.page = min(max(view.page + self.delta, 0), view.max_page)
        await view.edit_message(interaction)


class BrainFaxMailPageStatusButton(discord.ui.Button):
    def __init__(self, page: int, max_page: int) -> None:
        super().__init__(
            label=page_status_label(page + 1, max_page + 1),
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=True,
        )


class BrainFaxMailModeButton(discord.ui.Button):
    def __init__(self, label: str, mode: str, *, active: bool = False) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
            row=2,
            disabled=active,
        )
        self.mode = mode

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, BrainFaxMailView):
            await interaction.response.send_message("View unavailable.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        try:
            next_view = await view.refresh(mode=self.mode, page=0)
        except GovernorToolError as exc:
            LOGGER.warning("Fax Mail mode switch failed: %s", exc)
            await interaction.followup.send(_tool_failed("Fax Mail 불러오기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        _inherit_bound_view_state(view, next_view, getattr(interaction, "message", None))
        await interaction.edit_original_response(content=next_view.content(), view=next_view)


class BrainFaxMailCloseButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Close", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        view = self.view
        if isinstance(view, BrainServiceMessageView):
            await view.close_message(interaction.message)
            return
        await interaction.message.delete()
