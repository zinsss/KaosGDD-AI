from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from kaos_governor.documents import DocumentIntakeError, PaperlessSearchPage

from .access import AccessPolicy
from .inbox_formatting import rejection_message, render_paperless_search_expired, render_paperless_search_summary
from .markdown import NO_MENTIONS, escape_text


LOGGER = logging.getLogger(__name__)


class PaperlessSearchView(discord.ui.View):
    def __init__(self, inbox: Any | None, page: PaperlessSearchPage, policy: AccessPolicy, *, public_url: str = "") -> None:
        super().__init__(timeout=600)
        self.inbox = inbox
        self.page = page
        self.policy = policy
        self.public_url = public_url
        self._message: discord.Message | None = None
        previous_button = discord.ui.Button(
            label="←",
            style=discord.ButtonStyle.secondary,
            disabled=not inbox or page.page <= 1,
            custom_id="paperless-search:prev",
        )
        next_button = discord.ui.Button(
            label="→",
            style=discord.ButtonStyle.secondary,
            disabled=not inbox or page.page * page.page_size >= page.result_count,
            custom_id="paperless-search:next",
        )
        close_button = discord.ui.Button(
            label="Close",
            style=discord.ButtonStyle.secondary,
            custom_id="paperless-search:close",
        )
        previous_button.callback = self._page_callback(-1)
        next_button.callback = self._page_callback(1)
        close_button.callback = self._close_callback
        self.add_item(previous_button)
        self.add_item(next_button)
        self.add_item(close_button)

    def bind_message(self, message: discord.Message) -> None:
        self._message = message

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.edit(
                content=render_paperless_search_expired(self.page),
                view=None,
                allowed_mentions=NO_MENTIONS,
            )
        except discord.HTTPException:
            LOGGER.info("Could not clear expired Paperless search view %s", getattr(self._message, "id", ""))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    def _page_callback(self, direction: int):
        async def callback(interaction: discord.Interaction) -> None:
            if self.inbox is None:
                await interaction.response.send_message("Document list expired.", ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            next_page = max(1, self.page.page + direction)
            try:
                if self.page.query:
                    page = await asyncio.to_thread(self.inbox.paperless.search_page, self.page.query, limit=self.page.page_size, page=next_page)
                else:
                    page = await asyncio.to_thread(self.inbox.paperless.list_page, limit=self.page.page_size, page=next_page)
            except DocumentIntakeError as exc:
                await interaction.response.send_message(
                    f"Documents page failed: {escape_text(rejection_message(exc))}",
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
                return
            view = PaperlessSearchView(self.inbox, page, self.policy, public_url=self.public_url) if page.results else None
            await interaction.response.edit_message(
                content=render_paperless_search_summary(page, public_url=self.public_url),
                view=view,
                allowed_mentions=NO_MENTIONS,
            )
            if view is not None:
                view.bind_message(getattr(interaction, "message", None))

        return callback

    async def _close_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content=render_paperless_search_expired(self.page),
            view=None,
            allowed_mentions=NO_MENTIONS,
        )
