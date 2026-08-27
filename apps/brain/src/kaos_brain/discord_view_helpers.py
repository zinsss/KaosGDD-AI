from __future__ import annotations

import logging
from typing import Any, Callable

import discord

LOGGER = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()
BRAIN_SEARCH_WINDOW_SECONDS = 600
BRAIN_SERVICE_WINDOW_SECONDS = 600


def _bind_view_message(view: discord.ui.View | None, message: Any) -> None:
    bind = getattr(view, "bind_message", None)
    if callable(bind) and message is not None:
        bind(message)


def _inherit_bound_view_state(source: Any, target: discord.ui.View | None, message: Any | None = None) -> None:
    _bind_view_message(target, message or getattr(source, "_message", None))
    callback = getattr(source, "_close_callback", None)
    bind_callback = getattr(target, "bind_close_callback", None)
    if callable(callback) and callable(bind_callback):
        bind_callback(callback)


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
    def __init__(self, search_title: str, *, searched_from: str = "", close_on_timeout: bool = False) -> None:
        super().__init__(timeout=BRAIN_SEARCH_WINDOW_SECONDS)
        self.search_title = search_title.strip() or "search"
        self.searched_from = searched_from.strip()
        self.close_on_timeout = close_on_timeout
        self._message: discord.Message | None = None
        self._close_callback: Callable[[], None] | None = None

    def bind_message(self, message: discord.Message) -> None:
        self._message = message

    def bind_close_callback(self, callback: Callable[[], None]) -> None:
        self._close_callback = callback

    def _run_close_callback(self) -> None:
        if self._close_callback is not None:
            self._close_callback()

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
            await self._message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not close Brain search window %s", getattr(self._message, "id", ""))
        finally:
            self._message = None
            self._run_close_callback()

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            if self.close_on_timeout:
                await self._message.delete()
            else:
                await self._message.edit(
                    content=self._expired_notice(),
                    view=None,
                    allowed_mentions=NO_MENTIONS,
                )
        except discord.HTTPException:
            LOGGER.info("Could not expire Brain search window %s", getattr(self._message, "id", ""))
        finally:
            self._message = None
            if self.close_on_timeout:
                self._run_close_callback()


class BrainServiceMessageView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=BRAIN_SERVICE_WINDOW_SECONDS)
        self._message: Any | None = None
        self._close_callback: Callable[[], None] | None = None

    def bind_message(self, message: Any) -> None:
        self._message = message

    def bind_close_callback(self, callback: Callable[[], None]) -> None:
        self._close_callback = callback

    def _run_close_callback(self) -> None:
        if self._close_callback is not None:
            self._close_callback()

    async def close_message(self, message: Any | None = None) -> None:
        target = message or self._message
        if target is None:
            self._run_close_callback()
            self.stop()
            return
        try:
            await target.delete()
        except discord.HTTPException:
            LOGGER.info("Could not close Brain service message %s", getattr(target, "id", ""))
        finally:
            self._message = None
            self._run_close_callback()
            self.stop()

    async def on_timeout(self) -> None:
        await self.close_message()


class BrainCloseOnlyServiceView(BrainServiceMessageView):
    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await self.close_message(interaction.message)


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
