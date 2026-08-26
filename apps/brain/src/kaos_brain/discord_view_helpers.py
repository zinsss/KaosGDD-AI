from __future__ import annotations

import logging
from typing import Any

import discord

LOGGER = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()
BRAIN_SEARCH_WINDOW_SECONDS = 600


def _bind_view_message(view: discord.ui.View | None, message: Any) -> None:
    bind = getattr(view, "bind_message", None)
    if callable(bind) and message is not None:
        bind(message)


async def _reply_with_bound_view(
    message: discord.Message,
    content: str,
    *,
    view: discord.ui.View,
) -> None:
    sent = await message.reply(
        content,
        view=view,
        mention_author=False,
        allowed_mentions=NO_MENTIONS,
    )
    _bind_view_message(view, sent)


async def _followup_with_bound_view(
    interaction: discord.Interaction,
    content: str,
    *,
    view: discord.ui.View,
) -> None:
    sent = await interaction.followup.send(
        content,
        view=view,
        allowed_mentions=NO_MENTIONS,
        wait=True,
    )
    _bind_view_message(view, sent)


async def _defer_component_update(interaction: discord.Interaction) -> None:
    await interaction.response.defer()


async def _edit_deferred_component(
    interaction: discord.Interaction,
    *,
    content: str,
    view: discord.ui.View | None,
) -> None:
    _bind_view_message(view, getattr(interaction, "message", None))
    await interaction.edit_original_response(content=content, view=view, allowed_mentions=NO_MENTIONS)


class BrainTemporarySearchView(discord.ui.View):
    def __init__(self, search_title: str, *, searched_from: str = "") -> None:
        super().__init__(timeout=BRAIN_SEARCH_WINDOW_SECONDS)
        self.search_title = search_title.strip() or "search"
        self.searched_from = searched_from.strip()
        self._message: discord.Message | None = None

    def bind_message(self, message: discord.Message) -> None:
        self._message = message

    def _search_source_label(self) -> str:
        if self.searched_from == "Paperless and Memos":
            return "Paperless/Memos"
        return self.searched_from or "Search"

    def _closed_notice(self) -> str:
        return f"{self._search_source_label()} searched."

    def _expired_notice(self) -> str:
        return f"{self._search_source_label()} search expired."

    async def delete_message(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.edit(content=self._closed_notice(), view=None, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            LOGGER.info("Could not close Brain search window %s", getattr(self._message, "id", ""))
        finally:
            self._message = None

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.edit(
                content=self._expired_notice(),
                view=None,
                allowed_mentions=NO_MENTIONS,
            )
        except discord.HTTPException:
            LOGGER.info("Could not expire Brain search window %s", getattr(self._message, "id", ""))
        finally:
            self._message = None


class BrainAutoClosingView(discord.ui.View):
    def __init__(self, *, timeout: float | None = 600) -> None:
        super().__init__(timeout=timeout)
        self._message: Any | None = None

    def bind_message(self, message: Any) -> None:
        self._message = message

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not auto-close Brain temporary message %s", getattr(self._message, "id", ""))
        finally:
            self._message = None
