from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime

import discord
from kaos_governor import Actor, GovernorOperations
from kaos_governor.memos import (
    Memo,
    MemoMutationCommand,
    MemoMutationExecution,
    MemoMutationService,
    MemoSearchPage,
    MemoSearchResult,
    MemosError,
    MemosService,
)

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
        operations: GovernorOperations | None = None,
        memo_mutations: MemoMutationService | None = None,
    ) -> None:
        self.service = service
        self.policy = policy
        self.channel_id = channel_id
        self.confirmation_delete_after = confirmation_delete_after
        self.search_result_delete_after = search_result_delete_after
        self.operations = operations or GovernorOperations()
        self.memo_mutations = memo_mutations or MemoMutationService(service)
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

    async def create_memo(
        self,
        content: str,
        *,
        actor_id: str = "",
        idempotency_key: str = "",
    ) -> Memo:
        try:
            execution = await self._execute_memo_mutation(
                MemoMutationCommand("create", content=content),
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            memo = await self._memo_from_execution(execution)
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

    async def update_memo(
        self,
        name: str,
        content: str,
        *,
        actor_id: str = "",
        idempotency_key: str = "",
    ) -> Memo:
        try:
            execution = await self._execute_memo_mutation(
                MemoMutationCommand("edit", name=name, content=content),
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            memo = await self._memo_from_execution(execution)
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

    async def delete_memo(
        self,
        name: str,
        *,
        actor_id: str = "",
        idempotency_key: str = "",
    ) -> None:
        try:
            await self._execute_memo_mutation(
                MemoMutationCommand("delete", name=name),
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
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

    async def _execute_memo_mutation(
        self,
        command: MemoMutationCommand,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> MemoMutationExecution:
        clean_actor_id = str(actor_id or "").strip()
        actor = (
            Actor("user", clean_actor_id, "personal")
            if clean_actor_id
            else Actor("system", "discord-memos", "personal")
        )
        clean_idempotency_key = idempotency_key.strip() or (
            f"discord-surface:memos:{command.operation_type}:{secrets.token_hex(12)}"
        )
        return await asyncio.to_thread(
            self.memo_mutations.execute_governed,
            self.operations,
            command,
            actor=actor,
            idempotency_key=clean_idempotency_key,
        )

    async def _memo_from_execution(self, execution: MemoMutationExecution) -> Memo:
        record = execution.mutation.record
        if isinstance(record, Memo):
            return record
        return await asyncio.to_thread(self.service.get, execution.mutation.name)

    async def _handle_create(self, message: discord.Message, content: str) -> None:
        try:
            memo = await self.create_memo(
                content,
                actor_id=str(message.author.id),
                idempotency_key=f"discord-message:{message.id}",
            )
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
            if isinstance(view, MemosSearchView):
                view.bind_message(sent)
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

    async def close_search_message(self, message: discord.Message | None) -> None:
        if message is None:
            return
        self._temporary_search_messages.discard(int(message.id))
        await self._delete_message(message)

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
            memo = await self.capture.create_memo(
                str(self.memo.value or ""),
                actor_id=_interaction_actor_id(interaction),
                idempotency_key=_interaction_idempotency_key(interaction),
            )
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
        self._message: discord.Message | None = None
        self.add_item(MemosSearchSelect(page, capture))

    def bind_message(self, message: discord.Message) -> None:
        self._message = message

    async def on_timeout(self) -> None:
        if self._message is None:
            return
        try:
            await self._message.edit(view=None, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            LOGGER.info("Could not clear expired Memos search view %s", getattr(self._message, "id", ""))

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
        await interaction.response.defer()
        await interaction.followup.send(
            content=render_memo_opened(self.page.query, result),
            view=MemosOpenedView(self.capture, self.page.query, result.memo),
            allowed_mentions=NO_MENTIONS,
        )
        await self.capture.close_search_message(interaction.message)


class MemosOpenedView(discord.ui.View):
    def __init__(self, capture: DiscordMemosCapture, query: str, memo: Memo) -> None:
        super().__init__(timeout=600)
        self.capture = capture
        self.query = query
        self.memo = memo
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, custom_id="memos-open:close")
        more = discord.ui.Button(label="More...", style=discord.ButtonStyle.secondary, custom_id="memos-open:more")
        close.callback = self._close
        more.callback = self._more
        self.add_item(close)
        self.add_item(more)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.capture.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _close(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.message is not None:
            await interaction.message.delete()

    async def _more(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=MemosMoreView(self.capture, self.query, self.memo),
            allowed_mentions=NO_MENTIONS,
        )


class MemosMoreView(discord.ui.View):
    def __init__(self, capture: DiscordMemosCapture, query: str, memo: Memo) -> None:
        super().__init__(timeout=600)
        self.capture = capture
        self.query = query
        self.memo = memo
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, custom_id="memos-more:close")
        edit = discord.ui.Button(label="Edit", style=discord.ButtonStyle.primary, custom_id="memos-more:edit")
        delete = discord.ui.Button(label="Delete", style=discord.ButtonStyle.danger, custom_id="memos-more:delete")
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
        await interaction.response.edit_message(
            view=MemosEditConfirmView(self.capture, self.query, self.memo),
            allowed_mentions=NO_MENTIONS,
        )

    async def _delete(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=MemosDeleteConfirmView(self.capture, self.query, self.memo),
            allowed_mentions=NO_MENTIONS,
        )


class MemosEditConfirmView(discord.ui.View):
    def __init__(self, capture: DiscordMemosCapture, query: str, memo: Memo) -> None:
        super().__init__(timeout=600)
        self.capture = capture
        self.query = query
        self.memo = memo
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="memos-edit-confirm:cancel")
        confirm = discord.ui.Button(label="Edit Memo", style=discord.ButtonStyle.primary, custom_id="memos-edit-confirm:confirm")
        cancel.callback = self._cancel
        confirm.callback = self._confirm
        self.add_item(cancel)
        self.add_item(confirm)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.capture.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=MemosMoreView(self.capture, self.query, self.memo),
            allowed_mentions=NO_MENTIONS,
        )

    async def _confirm(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemosEditModal(self.capture, self.query, self.memo))


class MemosDeleteConfirmView(discord.ui.View):
    def __init__(self, capture: DiscordMemosCapture, query: str, memo: Memo) -> None:
        super().__init__(timeout=600)
        self.capture = capture
        self.query = query
        self.memo = memo
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="memos-delete-confirm:cancel")
        confirm = discord.ui.Button(label="Delete Memo", style=discord.ButtonStyle.danger, custom_id="memos-delete-confirm:confirm")
        cancel.callback = self._cancel
        confirm.callback = self._confirm
        self.add_item(cancel)
        self.add_item(confirm)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.capture.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=MemosMoreView(self.capture, self.query, self.memo),
            allowed_mentions=NO_MENTIONS,
        )

    async def _confirm(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.capture.delete_memo(
                self.memo.name,
                actor_id=_interaction_actor_id(interaction),
                idempotency_key=_interaction_idempotency_key(interaction),
            )
        except Exception:
            await interaction.followup.send(
                f"Memos delete rejected: {self.capture.last_error or 'internal_error'}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        if interaction.message is not None:
            await interaction.message.edit(
                content=render_memo_deleted(self.memo),
                view=MemosDeletedView(self.capture, self.query, self.memo),
                allowed_mentions=NO_MENTIONS,
            )


class MemosDeletedView(discord.ui.View):
    def __init__(self, capture: DiscordMemosCapture, query: str, memo: Memo) -> None:
        super().__init__(timeout=600)
        self.capture = capture
        self.query = query
        self.memo = memo
        undo = discord.ui.Button(label="Undo Delete", style=discord.ButtonStyle.primary, custom_id="memos-deleted:undo")
        delete_message = discord.ui.Button(
            label="Delete this Message",
            style=discord.ButtonStyle.danger,
            custom_id="memos-deleted:delete-message",
        )
        undo.callback = self._undo
        delete_message.callback = self._delete_message
        self.add_item(undo)
        self.add_item(delete_message)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.capture.policy.allows(interaction.guild_id, interaction.channel_id, interaction.user.id):
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    async def _undo(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            memo = await self.capture.create_memo(
                self.memo.content,
                actor_id=_interaction_actor_id(interaction),
                idempotency_key=_interaction_idempotency_key(interaction),
            )
        except Exception:
            await interaction.followup.send(
                f"Memos restore rejected: {self.capture.last_error or 'internal_error'}",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        if interaction.message is not None:
            await interaction.message.edit(
                content=render_memo_opened(self.query, MemoSearchResult(memo, "")),
                view=MemosOpenedView(self.capture, self.query, memo),
                allowed_mentions=NO_MENTIONS,
            )

    async def _delete_message(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
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
            memo = await self.capture.update_memo(
                self.memo.name,
                str(self.content.value or ""),
                actor_id=_interaction_actor_id(interaction),
                idempotency_key=_interaction_idempotency_key(interaction),
            )
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


def _interaction_actor_id(interaction: discord.Interaction) -> str:
    return str(getattr(getattr(interaction, "user", None), "id", "") or "")


def _interaction_idempotency_key(interaction: discord.Interaction) -> str:
    interaction_id = str(getattr(interaction, "id", "") or "")
    return f"discord-interaction:{interaction_id}" if interaction_id else ""


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
    content = discord.utils.escape_mentions(memo.content).strip()
    return (content or f"-# {escape_text(memo.name)}")[:1990]


def render_memo_deleted(memo: Memo) -> str:
    content = discord.utils.escape_mentions(memo.content).strip()
    deleted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    if content:
        lines.append(content)
    lines.append(f"Deleted at {deleted_at}")
    return "\n\n".join(lines)[:1990]


def memo_option_label(result: MemoSearchResult) -> str:
    return compact_select_text(memo_title(result.memo), 100)


def memo_option_description(result: MemoSearchResult) -> str:
    tags = tuple(tag.strip().lstrip("#") for tag in result.memo.tags if tag.strip())
    if not tags:
        return "No tags"
    return compact_select_text(", ".join(f"#{tag}" for tag in tags), 100)


def memo_title(memo: Memo) -> str:
    for raw in memo.content.splitlines():
        title = raw.strip().lstrip("#").strip()
        if title:
            return title
    return memo.name


def compact_select_text(value: str, limit: int) -> str:
    text = " ".join(value.split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
