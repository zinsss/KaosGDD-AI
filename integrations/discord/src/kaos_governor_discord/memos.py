from __future__ import annotations

import asyncio
import logging

import discord
from kaos_governor.memos import MemoSearchPage, MemoSearchResult, MemosError, MemosService

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
    ) -> None:
        self.service = service
        self.policy = policy
        self.channel_id = channel_id
        self.confirmation_delete_after = confirmation_delete_after
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
        view = MemosSearchView(page, self.policy) if len(page.results) > 1 else None
        if len(page.results) == 1:
            content = render_memo_opened(page.query, page.results[0])
        await message.channel.send(content, view=view, allowed_mentions=NO_MENTIONS)
        self.last_error = ""

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete captured Memos message %s", getattr(message, "id", ""))


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
    def __init__(self, page: MemoSearchPage, policy: AccessPolicy) -> None:
        super().__init__(timeout=600)
        self.page = page
        self.policy = policy
        self.add_item(MemosSearchSelect(page))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class MemosSearchSelect(discord.ui.Select):
    def __init__(self, page: MemoSearchPage) -> None:
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

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            index = int(self.values[0])
            result = self.page.results[index]
        except (IndexError, TypeError, ValueError):
            await interaction.response.send_message("Memo selection expired.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.edit_message(
            content=render_memo_opened(self.page.query, result),
            view=None,
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
