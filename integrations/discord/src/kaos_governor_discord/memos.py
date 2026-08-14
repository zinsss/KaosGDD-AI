from __future__ import annotations

import asyncio
import logging

import discord
from kaos_governor.memos import Memo, MemoSearchPage, MemoSearchResult, MemosError, MemosService

from .access import AccessPolicy
from .markdown import NO_MENTIONS, escape_text
from .search import normalize_dotdot_query


LOGGER = logging.getLogger(__name__)


class DiscordMemosCapture:
    def __init__(
        self,
        service: MemosService,
        policy: AccessPolicy,
        *,
        channel_id: int,
        confirmation_delete_after: float = 5.0,
        search_result_delete_after: float = 1800.0,
    ) -> None:
        self.service = service
        self.policy = policy
        self.channel_id = channel_id
        self.confirmation_delete_after = confirmation_delete_after
        self.search_result_delete_after = search_result_delete_after
        self._temporary_search_messages: set[int] = set()
        self.accepted_count = 0
        self.rejected_count = 0
        self.last_error = ""

    async def handle_message(self, message: discord.Message) -> bool:
        if message.channel.id != self.channel_id:
            return False
        if message.author.bot:
            return True
        if not self.policy.allows(message.guild.id if message.guild else None, message.channel.id, message.author.id):
            LOGGER.warning("Rejected Memos capture channel=%s user=%s", message.channel.id, message.author.id)
            self.rejected_count += 1
            return True
        content = message.content.strip()
        if not content:
            return True
        if content.startswith(".."):
            await self._handle_search(message, content[2:].strip())
            return True
        memo_content = parse_create_memo_message(str(message.content or ""))
        if memo_content is None:
            await self._delete_message(message)
            return True
        if not memo_content:
            await self._delete_message(message)
            await message.channel.send(
                "## Memos\n- Add memo",
                view=MemosCreatePromptView(self),
                allowed_mentions=NO_MENTIONS,
            )
            return True
        await self._handle_create(message, memo_content)
        return True

    async def create_memo(self, content: str):
        try:
            memo = await asyncio.to_thread(self.service.create, content)
        except (ValueError, MemosError) as exc:
            self.rejected_count += 1
            self.last_error = exc.code if isinstance(exc, MemosError) else str(exc)
            raise
        except Exception as exc:
            self.rejected_count += 1
            self.last_error = type(exc).__name__
            LOGGER.exception("Unexpected Memos capture failure")
            raise
        self.accepted_count += 1
        self.last_error = ""
        return memo

    async def update_memo(self, name: str, content: str) -> Memo:
        try:
            memo = await asyncio.to_thread(self.service.update, name, content)
        except (ValueError, MemosError) as exc:
            self.rejected_count += 1
            self.last_error = exc.code if isinstance(exc, MemosError) else str(exc)
            raise
        except Exception as exc:
            self.rejected_count += 1
            self.last_error = type(exc).__name__
            LOGGER.exception("Unexpected Memos update failure")
            raise
        self.last_error = ""
        return memo

    async def delete_memo(self, name: str) -> None:
        try:
            await asyncio.to_thread(self.service.delete, name)
        except (ValueError, MemosError) as exc:
            self.rejected_count += 1
            self.last_error = exc.code if isinstance(exc, MemosError) else str(exc)
            raise
        except Exception as exc:
            self.rejected_count += 1
            self.last_error = type(exc).__name__
            LOGGER.exception("Unexpected Memos delete failure")
            raise
        self.last_error = ""

    async def _handle_create(self, message: discord.Message, content: str) -> None:
        try:
            memo = await self.create_memo(content)
        except (ValueError, MemosError):
            await message.reply(
                f"Memos rejected: {self.last_error}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        except Exception:
            await message.reply("Memos rejected: internal_error", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await self._delete_message(message)
        await message.channel.send(
            f"Saved to Memos: {memo.name}",
            delete_after=self.confirmation_delete_after,
            allowed_mentions=NO_MENTIONS,
        )

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "acceptedCount": self.accepted_count,
            "rejectedCount": self.rejected_count,
            "searchResultDeleteAfterSeconds": self.search_result_delete_after,
            "lastError": self.last_error,
        }

    async def _handle_search(self, message: discord.Message, query: str) -> None:
        normalized_query = normalize_dotdot_query(query)
        try:
            limit = min(25, self.service.config.max_results)
            page = await asyncio.to_thread(self.service.search_page, normalized_query, None, limit)
        except (ValueError, MemosError) as exc:
            self.rejected_count += 1
            self.last_error = exc.code if isinstance(exc, MemosError) else str(exc)
            await message.reply(
                f"Memos search rejected: {self.last_error}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        except Exception as exc:
            self.rejected_count += 1
            self.last_error = type(exc).__name__
            LOGGER.exception("Unexpected Memos search failure")
            await message.reply(
                "Memos search rejected: internal_error",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await self._delete_message(message)
        content = render_memos_search_summary(page)
        view: discord.ui.View | None = MemosSearchView(page, self) if len(page.results) > 1 else None
        if len(page.results) == 1:
            content = render_memo_opened(page.query, page.results[0])
            view = MemosOpenedView(self, page.query, page.results[0].memo)
        sent = await message.channel.send(content, view=view, allowed_mentions=NO_MENTIONS)
        if len(page.results) != 1:
            self._track_temporary_search_message(sent)
        self.last_error = ""

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete captured Memos message %s", getattr(message, "id", ""))

    def preserve_search_message(self, message: discord.Message | None) -> None:
        if message is not None:
            self._temporary_search_messages.discard(int(message.id))

    def _track_temporary_search_message(self, message: discord.Message) -> None:
        if self.search_result_delete_after <= 0:
            return
        message_id = int(message.id)
        self._temporary_search_messages.add(message_id)
        asyncio.create_task(
            self._delete_temporary_search_message(message, self.search_result_delete_after),
            name=f"memos-search-cleanup-{message_id}",
        )

    async def _delete_temporary_search_message(self, message: discord.Message, delay: float) -> None:
        await asyncio.sleep(delay)
        message_id = int(message.id)
        if message_id not in self._temporary_search_messages:
            return
        self._temporary_search_messages.discard(message_id)
        await self._delete_message(message)


class MemosCreatePromptView(discord.ui.View):
    def __init__(self, capture: DiscordMemosCapture) -> None:
        super().__init__(timeout=600)
        self.capture = capture
        button = discord.ui.Button(
            label="Add Memo",
            style=discord.ButtonStyle.primary,
            custom_id="memos-create:open",
        )
        button.callback = self._open_modal
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.capture.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _open_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemosCreateModal(self.capture))


class MemosCreateModal(discord.ui.Modal):
    def __init__(self, capture: DiscordMemosCapture) -> None:
        super().__init__(title="Add Memo", timeout=600)
        self.capture = capture
        self.memo = discord.ui.TextInput(
            label="Memo",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
            custom_id="memos-create:content",
        )
        self.add_item(self.memo)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            memo = await self.capture.create_memo(str(self.memo.value or ""))
        except Exception:
            await interaction.response.send_message(
                f"Memos rejected: {self.capture.last_error or 'internal_error'}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await interaction.response.send_message(
            f"Saved to Memos: {memo.name}",
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )


class MemosSearchView(discord.ui.View):
    def __init__(self, page: MemoSearchPage, capture: DiscordMemosCapture) -> None:
        super().__init__(timeout=600)
        self.page = page
        self.capture = capture
        self.add_item(MemosSearchSelect(page, capture))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.capture.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class MemosSearchSelect(discord.ui.Select):
    def __init__(self, page: MemoSearchPage, capture: DiscordMemosCapture) -> None:
        options = [
            discord.SelectOption(
                label=memo_option_label(result),
                description=memo_option_description(result),
                value=str(index),
            )
            for index, result in enumerate(page.results[:25])
        ]
        super().__init__(
            placeholder="Open memo",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="memos-search:open",
        )
        self.page = page
        self.capture = capture

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            index = int(self.values[0])
            result = self.page.results[index]
        except (IndexError, TypeError, ValueError):
            await interaction.response.send_message("Memo selection expired.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        self.capture.preserve_search_message(interaction.message)
        await interaction.response.edit_message(
            content=render_memo_opened(self.page.query, result),
            view=MemosOpenedView(self.capture, self.page.query, result.memo),
            allowed_mentions=NO_MENTIONS,
        )


class MemosOpenedView(discord.ui.View):
    def __init__(self, capture: DiscordMemosCapture, query: str, memo: Memo) -> None:
        super().__init__(timeout=600)
        self.capture = capture
        self.query = query
        self.memo = memo
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, custom_id="memos-open:close")
        edit = discord.ui.Button(label="Edit", style=discord.ButtonStyle.primary, custom_id="memos-open:edit")
        delete = discord.ui.Button(label="Delete", style=discord.ButtonStyle.danger, custom_id="memos-open:delete")
        close.callback = self._close
        edit.callback = self._edit
        delete.callback = self._delete
        self.add_item(close)
        self.add_item(edit)
        self.add_item(delete)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.capture.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.message is not None:
            await interaction.message.delete()

    async def _edit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemosEditModal(self.capture, self.query, self.memo))

    async def _delete(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.capture.delete_memo(self.memo.name)
        except Exception:
            await interaction.followup.send(
                f"Memos delete rejected: {self.capture.last_error or 'internal_error'}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        if interaction.message is not None:
            await interaction.message.delete()


class MemosEditModal(discord.ui.Modal):
    def __init__(self, capture: DiscordMemosCapture, query: str, memo: Memo) -> None:
        super().__init__(title="Edit Memo", timeout=600)
        self.capture = capture
        self.query = query
        self.memo = memo
        self.content = discord.ui.TextInput(
            label="Memo",
            style=discord.TextStyle.paragraph,
            required=True,
            default=memo.content[:4000],
            max_length=4000,
            custom_id="memos-edit:content",
        )
        self.add_item(self.content)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            memo = await self.capture.update_memo(self.memo.name, str(self.content.value or ""))
        except Exception:
            await interaction.followup.send(
                f"Memos edit rejected: {self.capture.last_error or 'internal_error'}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        result = MemoSearchResult(memo, "")
        if interaction.message is not None:
            await interaction.message.edit(
                content=render_memo_opened(self.query, result),
                view=MemosOpenedView(self.capture, self.query, memo),
                allowed_mentions=NO_MENTIONS,
            )


def parse_create_memo_message(content: str) -> str | None:
    stripped = content.strip()
    if stripped == "+++":
        return ""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "+++":
        return None
    return "\n".join(lines[1:]).strip()


def render_memos_search_summary(page: MemoSearchPage) -> str:
    lines = [
        "Searched..",
        f"## {escape_text(page.query or '..')}",
        f"{page.result_count} results in {page.total_count} memos",
    ]
    if not page.results:
        lines.append("- No matching memos.")
    elif page.result_count > len(page.results):
        lines.append(f"- Showing first {len(page.results)} results.")
    return "\n".join(lines)[:1990]


def render_memo_opened(query: str, result: MemoSearchResult) -> str:
    memo = result.memo
    lines = [
        f"## Memos search · {escape_text(query or '..')}",
        f"-# {escape_text(memo.name)}",
    ]
    content = discord.utils.escape_mentions(memo.content).strip()
    if content:
        lines.append(content)
    return "\n".join(lines)[:1990]


def memo_option_label(result: MemoSearchResult) -> str:
    content = " ".join(result.memo.content.split())
    for raw in result.memo.content.splitlines():
        title = raw.strip().lstrip("#").strip()
        if title:
            return title[:100]
    return (content or result.memo.name)[:100]


def memo_option_description(result: MemoSearchResult) -> str:
    snippet = " ".join((result.snippet or result.memo.content).split())
    return snippet[:100]
