from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import discord

from .discord_formatting import (
    KST,
    _payload_count,
    _render_document_list_message,
    _render_memo_list_message,
)
from .discord_view_helpers import (
    NO_MENTIONS,
    BrainAutoClosingView,
    BrainTemporarySearchView,
    _bind_view_message,
    _defer_component_update,
    _edit_deferred_component,
    _followup_with_bound_view,
    _inherit_bound_view_state,
)
from .governor_tools import (
    GovernorToolClient,
    GovernorToolError,
    SEARCH_RESULT_LIMIT,
    document_option_description,
    document_option_label,
    document_public_url,
    memo_option_description,
    memo_option_label,
    memo_public_url,
    render_document_opened,
    render_memo_deleted,
    render_memo_opened,
    search_results,
)
from .list_formatting import page_status_label
from .memo_intent import MemoCreateRequest

LOGGER = logging.getLogger(__name__)


def _tool_failed(action: str) -> str:
    return f"{action} 실패했어요."


def _settings_value(target: object, name: str) -> str:
    settings = getattr(target, "settings", None)
    return str(getattr(settings, name, "") or "")


def _linked_document_results(results: list[dict[str, Any]], paperless_public_url: str) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "url": item.get("url") or item.get("publicUrl") or document_public_url(paperless_public_url, item.get("id")),
        }
        for item in results
    ]


class BrainMemoSearchView(BrainTemporarySearchView):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        query: str,
        results: list[dict[str, Any]],
        *,
        result_count: int = 0,
        total_count: int = 0,
        memos_public_url: str = "",
        close_on_timeout: bool = False,
    ) -> None:
        super().__init__(query, searched_from="Memos", close_on_timeout=close_on_timeout)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.results = results[:SEARCH_RESULT_LIMIT]
        self.result_count = result_count or len(results)
        self.total_count = total_count or self.result_count
        self.memos_public_url = memos_public_url
        self.add_item(BrainMemoSearchSelect(self))
        self.add_item(BrainSearchCloseButton(row=1))

    def content(self, *, searched: bool = False) -> str:
        return _render_memo_list_message(
            self.query,
            self.results,
            result_count=self.result_count,
            total_count=self.total_count,
            searched=searched,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainMemoSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainMemoSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=memo_option_label(item),
                description=memo_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.results)
        ]
        end = len(parent.results)
        placeholder = f"Memos {1 if end else 0}-{end}" if end else "Memos 0"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_memo(str(item.get("name") or ""))
            memo = payload.get("memo")
            if isinstance(memo, dict):
                item = {**item, **memo, "full": True}
            content = render_memo_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Memo open failed: %s", exc)
            content = _tool_failed("메모 열기")
            await interaction.response.send_message(content, ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            content,
            view=BrainOpenedMemoView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                str(item.get("name") or ""),
                content,
                memo_public_url(self.parent_view.memos_public_url, str(item.get("name") or "")),
            ),
        )


class BrainSearchCloseButton(discord.ui.Button):
    def __init__(self, *, row: int = 1) -> None:
        super().__init__(label="Close", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, BrainTemporarySearchView):
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await parent.delete_message()
        parent.stop()


class BrainCombinedSearchView(BrainTemporarySearchView):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        query: str,
        memo_results: list[dict[str, Any]],
        document_results: list[dict[str, Any]],
        *,
        memo_count: int = 0,
        memo_total: int = 0,
        document_count: int = 0,
        document_total: int = 0,
        paperless_public_url: str = "",
        memos_public_url: str = "",
    ) -> None:
        super().__init__(query, searched_from="Paperless and Memos")
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.memo_results = memo_results[:SEARCH_RESULT_LIMIT]
        self.document_results = document_results[:SEARCH_RESULT_LIMIT]
        self.memo_count = memo_count or len(memo_results)
        self.memo_total = memo_total or self.memo_count
        self.document_count = document_count or len(document_results)
        self.document_total = document_total or self.document_count
        self.paperless_public_url = paperless_public_url
        self.memos_public_url = memos_public_url
        if self.memo_results:
            self.add_item(BrainCombinedMemoSearchSelect(self))
        if self.document_results:
            self.add_item(BrainCombinedDocumentSearchSelect(self))
        if self.document_results:
            self.add_item(BrainCombinedSearchFullButton("Paperless", "documents"))
        if self.memo_results:
            self.add_item(BrainCombinedSearchFullButton("Memos", "memos"))
        self.add_item(BrainSearchCloseButton(row=3))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainCombinedMemoSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainCombinedSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=memo_option_label(item),
                description=memo_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.memo_results)
        ]
        end = len(parent.memo_results)
        placeholder = f"Memos {1 if end else 0}-{end} of {parent.memo_count}" if end else "Memos 0"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.memo_results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_memo(str(item.get("name") or ""))
            memo = payload.get("memo")
            if isinstance(memo, dict):
                item = {**item, **memo, "full": True}
            content = render_memo_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Memo open failed: %s", exc)
            await interaction.response.send_message(_tool_failed("메모 열기"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            content,
            view=BrainOpenedMemoView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                str(item.get("name") or ""),
                content,
                memo_public_url(self.parent_view.memos_public_url, str(item.get("name") or "")),
            ),
        )


class BrainCombinedDocumentSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainCombinedSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=document_option_label(item),
                description=document_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.document_results)
        ]
        end = len(parent.document_results)
        placeholder = f"Paperless {1 if end else 0}-{end} of {parent.document_count}" if end else "Paperless 0"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.document_results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_document(item.get("id"))
            document = payload.get("document")
            if isinstance(document, dict):
                item = {**item, **document, "full": True}
            content = render_document_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Document open failed: %s", exc)
            content = _tool_failed("문서 열기")
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            content,
            view=BrainOpenedDocumentView(
                self.parent_view.actor_id,
                document_public_url(self.parent_view.paperless_public_url, item.get("id")) if "item" in locals() else "",
            ),
        )


class BrainCombinedSearchFullButton(discord.ui.Button):
    def __init__(self, label: str, target: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.target = target

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, BrainCombinedSearchView):
            await interaction.response.send_message(_tool_failed("조회"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if self.target == "documents":
            view: discord.ui.View = BrainDocumentSearchView(
                parent.governor_tools,
                parent.actor_id,
                parent.query,
                parent.document_results,
                result_count=parent.document_count,
                total_count=parent.document_total,
                page=1,
                page_size=SEARCH_RESULT_LIMIT,
                searched=True,
                paperless_public_url=parent.paperless_public_url,
            )
            view.bind_message(interaction.message)  # type: ignore[arg-type]
            await interaction.response.edit_message(
                content=view.content(),  # type: ignore[attr-defined]
                view=view,
                allowed_mentions=NO_MENTIONS,
            )
            parent.stop()
            return

        content = _render_memo_list_message(
            parent.query,
            parent.memo_results,
            result_count=parent.memo_count,
            total_count=parent.memo_total,
            searched=True,
        )
        view = BrainMemoSearchView(
            parent.governor_tools,
            parent.actor_id,
            parent.query,
            parent.memo_results,
            result_count=parent.memo_count,
            total_count=parent.memo_total,
            memos_public_url=parent.memos_public_url,
        )
        view.bind_message(interaction.message)  # type: ignore[arg-type]
        await interaction.response.edit_message(content=content, view=view, allowed_mentions=NO_MENTIONS)
        parent.stop()


class BrainOpenedMemoView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str, url: str = "") -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content
        self.url = url
        if url:
            self.add_item(discord.ui.Button(label="Open memo", style=discord.ButtonStyle.link, url=url))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()

    @discord.ui.button(label="More...", style=discord.ButtonStyle.secondary)
    async def more(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoActionsView(self.governor_tools, self.actor_id, self.name, self.content, self.url)
        _bind_view_message(view, interaction.message)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainOpenedMemoActionsView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str, url: str = "") -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content
        self.url = url

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainMemoEditConfirmView(self.governor_tools, self.actor_id, self.name, self.content, self.url)
        _bind_view_message(view, interaction.message)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainMemoDeleteConfirmView(self.governor_tools, self.actor_id, self.name, self.content, self.url)
        _bind_view_message(view, interaction.message)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainMemoEditConfirmView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str, url: str = "") -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content
        self.url = url

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Edit Memo", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            BrainMemoEditModal(self.governor_tools, self.actor_id, self.name, self.content, interaction.message, self.url)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, self.content, self.url)
        _bind_view_message(view, interaction.message)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainMemoEditModal(discord.ui.Modal, title="Edit memo"):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        name: str,
        content: str,
        source_message: discord.Message | None,
        url: str = "",
    ) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.source_message = source_message
        self.url = url
        self.content_input = discord.ui.TextInput(
            label="Memo",
            style=discord.TextStyle.paragraph,
            default=content[:4000],
            max_length=4000,
            required=True,
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        content = str(self.content_input.value).strip()
        await interaction.response.defer(ephemeral=True)
        try:
            proposal = await self.governor_tools.propose_memo_edit_by_name(
                self.name,
                content,
                actor_id=self.actor_id,
                idempotency_key=f"brain-memo-edit-{interaction.id}",
            )
            payload = await self.governor_tools.approve_confirmation(
                str(proposal.get("confirmationId") or ""),
                actor_id=self.actor_id,
            )
            memo = payload.get("memo")
            if isinstance(memo, dict):
                content = str(memo.get("content") or content)
        except GovernorToolError as exc:
            LOGGER.warning("Memo edit failed: %s", exc)
            await interaction.followup.send(_tool_failed("메모 수정"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if self.source_message is not None:
            view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, content, self.url)
            await self.source_message.edit(content=content[:1900], view=view, allowed_mentions=NO_MENTIONS)
            return
        await interaction.followup.send(
            content[:1900],
            view=BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, content, self.url),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )


class BrainMemoDeleteConfirmView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str, url: str = "") -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content
        self.url = url

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Delete Memo", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            proposal = await self.governor_tools.propose_memo_delete_by_name(
                self.name,
                actor_id=self.actor_id,
                idempotency_key=f"brain-memo-delete-{interaction.id}",
            )
            await self.governor_tools.approve_confirmation(str(proposal.get("confirmationId") or ""), actor_id=self.actor_id)
        except GovernorToolError as exc:
            LOGGER.warning("Memo delete failed: %s", exc)
            await _edit_deferred_component(interaction, content=_tool_failed("메모 삭제"), view=self)
            return
        deleted_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        view = BrainDeletedMemoView(self.governor_tools, self.actor_id, self.content)
        await _edit_deferred_component(interaction, content=render_memo_deleted(self.content, deleted_at), view=view)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, self.content, self.url)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainDeletedMemoView(BrainAutoClosingView):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Undo Delete", style=discord.ButtonStyle.primary)
    async def undo(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _defer_component_update(interaction)
        try:
            proposal = await self.governor_tools.propose_memo_create(
                MemoCreateRequest(self.content),
                actor_id=self.actor_id,
                idempotency_key=f"brain-memo-undo-delete-{interaction.id}",
            )
            payload = await self.governor_tools.approve_confirmation(
                str(proposal.get("confirmationId") or ""),
                actor_id=self.actor_id,
            )
            memo = payload.get("memo")
            name = str(memo.get("name") or "") if isinstance(memo, dict) else ""
            content = str(memo.get("content") or self.content) if isinstance(memo, dict) else self.content
        except GovernorToolError as exc:
            LOGGER.warning("Memo restore failed: %s", exc)
            await _edit_deferred_component(interaction, content=_tool_failed("메모 복구"), view=self)
            return
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, name, content)
        await _edit_deferred_component(interaction, content=content[:1900], view=view)
        self.stop()

    @discord.ui.button(label="Delete this Message", style=discord.ButtonStyle.danger)
    async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message(_tool_failed("메시지 삭제"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()


class BrainDocumentSearchView(BrainTemporarySearchView):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        query: str,
        results: list[dict[str, Any]],
        *,
        result_count: int = 0,
        total_count: int = 0,
        page: int = 1,
        page_size: int = SEARCH_RESULT_LIMIT,
        searched: bool = False,
        paperless_public_url: str = "",
        close_on_timeout: bool = False,
    ) -> None:
        super().__init__(query, searched_from="Paperless", close_on_timeout=close_on_timeout)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.page = max(1, page)
        self.page_size = max(1, page_size)
        self.result_count = result_count or len(results)
        self.total_count = total_count or self.result_count
        self.results = results[: self.page_size]
        self.searched = searched
        self.paperless_public_url = paperless_public_url
        self._rebuild_items()

    @property
    def page_total(self) -> int:
        return max(1, (self.result_count + self.page_size - 1) // self.page_size)

    def content(self, *, searched: bool | None = None) -> str:
        return _render_document_list_message(
            self.query,
            self.results,
            result_count=self.result_count,
            total_count=self.total_count,
            page=self.page,
            page_size=self.page_size,
            searched=self.searched if searched is None else searched,
        )

    def _rebuild_items(self) -> None:
        self.clear_items()
        self.add_item(BrainDocumentSearchSelect(self))
        if self.page_total > 1:
            self.add_item(BrainDocumentPageButton("←", -1, disabled=self.page <= 1))
            self.add_item(BrainDocumentPageStatusButton(self.page, self.page_total))
            self.add_item(BrainDocumentPageButton("→", 1, disabled=self.page >= self.page_total))
        self.add_item(BrainSearchCloseButton(row=2))

    async def fetch_page(self, page: int) -> BrainDocumentSearchView:
        payload = await self.governor_tools.documents(self.query, page=page, limit=self.page_size)
        results = _linked_document_results(search_results(payload), self.paperless_public_url)
        return BrainDocumentSearchView(
            self.governor_tools,
            self.actor_id,
            self.query,
            results,
            result_count=_payload_count(payload, "resultCount", "count", fallback=len(results)),
            total_count=_payload_count(payload, "totalCount", "total", fallback=len(results)),
            page=_payload_count(payload, "page", fallback=page),
            page_size=_payload_count(payload, "pageSize", "page_size", fallback=self.page_size),
            searched=self.searched,
            paperless_public_url=self.paperless_public_url,
            close_on_timeout=self.close_on_timeout,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainDocumentSearchSelect(discord.ui.Select):
    def __init__(self, parent: BrainDocumentSearchView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=document_option_label(item),
                description=document_option_description(item) or None,
                value=str(index),
            )
            for index, item in enumerate(parent.results)
        ]
        start = (parent.page - 1) * parent.page_size + 1 if parent.results else 0
        end = start + len(parent.results) - 1 if parent.results else 0
        placeholder = f"Paperless {start}-{end}" if parent.results else "Paperless 0"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_document(item.get("id"))
            document = payload.get("document")
            if isinstance(document, dict):
                item = {**item, **document, "full": True}
            content = render_document_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("Document open failed: %s", exc)
            content = _tool_failed("문서 열기")
        await interaction.response.defer()
        await _followup_with_bound_view(
            interaction,
            content,
            view=BrainOpenedDocumentView(
                self.parent_view.actor_id,
                document_public_url(self.parent_view.paperless_public_url, item.get("id")) if "item" in locals() else "",
            ),
        )


class BrainDocumentPageButton(discord.ui.Button):
    def __init__(self, label: str, delta: int, *, disabled: bool = False) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled, row=1)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, BrainDocumentSearchView):
            await interaction.response.send_message(_tool_failed("문서 목록"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        try:
            next_view = await parent.fetch_page(parent.page + self.delta)
        except GovernorToolError as exc:
            LOGGER.warning("Document page fetch failed: %s", exc)
            await interaction.followup.send(_tool_failed("문서 목록"), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        _inherit_bound_view_state(parent, next_view, interaction.message)
        await interaction.edit_original_response(content=next_view.content(), view=next_view, allowed_mentions=NO_MENTIONS)
        parent.stop()


class BrainDocumentPageStatusButton(discord.ui.Button):
    def __init__(self, page: int, page_total: int) -> None:
        super().__init__(label=page_status_label(page, page_total), style=discord.ButtonStyle.secondary, disabled=True, row=1)


class BrainOpenedDocumentView(BrainAutoClosingView):
    def __init__(self, actor_id: int, url: str = "") -> None:
        super().__init__(timeout=600)
        self.actor_id = actor_id
        if url:
            self.add_item(discord.ui.Button(label="Open document", style=discord.ButtonStyle.link, url=url))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.message.delete()
