from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

import discord

from .config import Settings
from .event_intent import EventCreateRequest, parse_event_create
from .governor_tools import (
    GovernorToolClient,
    GovernorToolConfig,
    GovernorToolError,
    TaskEditRequest,
    document_option_description,
    document_option_label,
    memo_option_description,
    memo_option_label,
    render_memo_create_completed,
    render_memo_create_proposal,
    render_memo_delete_completed,
    render_memo_delete_proposal,
    render_memo_deleted,
    render_memo_edit_completed,
    render_memo_edit_proposal,
    render_document_opened,
    render_event_create_completed,
    render_event_create_proposal,
    render_memo_opened,
    render_task_action_completed,
    render_task_action_proposal,
    render_task_create_completed,
    render_task_create_proposal,
    render_task_edit_completed,
    render_task_edit_proposal,
    render_task_due_update_completed,
    render_task_due_update_proposal,
    render_tool_context,
    search_results,
)
from .intent import Route, parse_request
from .memo_intent import MemoCreateRequest, MemoDeleteRequest, MemoEditRequest, parse_memo_create, parse_memo_delete, parse_memo_edit
from .ollama import OllamaClient, OllamaConfig, OllamaError
from .task_update_intent import (
    TaskActionRequest,
    TaskCreateRequest,
    TaskDueUpdateRequest,
    parse_task_action,
    parse_task_create,
    parse_task_due_update,
)
from .tool_intent import ToolKind, ToolRequest, parse_tool_request

LOGGER = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()
KST = ZoneInfo("Asia/Seoul")


class BrainBot(discord.Client):
    def __init__(self, settings: Settings, ollama: OllamaClient | None = None) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=NO_MENTIONS)
        self.settings = settings
        self.ollama = ollama or OllamaClient(
            OllamaConfig(
                base_url=settings.ollama_base_url,
                chat_model=settings.chat_model,
                deep_model=settings.deep_model,
                timeout_seconds=settings.request_timeout_seconds,
            )
        )
        self.governor_tools = (
            GovernorToolClient(
                GovernorToolConfig(
                    base_url=settings.governor_tools_base_url,
                    api_token=settings.governor_tools_api_token,
                    profile=settings.governor_tools_profile,
                    supplies_collection_id=settings.governor_tools_supplies_collection_id,
                    timeout_seconds=settings.governor_tools_timeout_seconds,
                )
            )
            if settings.governor_tools_enabled
            else None
        )

    async def on_ready(self) -> None:
        LOGGER.info("KaosBrain connected as %s", self.user)

    def _allowed(self, message: discord.Message) -> bool:
        return (
            message.guild is not None
            and message.guild.id == self.settings.guild_id
            and message.channel.id == self.settings.brain_channel_id
            and message.author.id in self.settings.allowed_user_ids
        )

    def _strip_mention(self, message: discord.Message) -> str:
        content = message.content.strip()
        if self.user is None:
            return content
        mention_forms = {f"<@{self.user.id}>", f"<@!{self.user.id}>"}
        for mention in mention_forms:
            content = content.replace(mention, "").strip()
        return content

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not self._allowed(message):
            return
        mentioned = self.user is not None and self.user in message.mentions
        if not self.settings.respond_without_mention and not mentioned:
            return
        request = parse_request(self._strip_mention(message))
        if request is None:
            return
        task_update = (
            parse_task_due_update(request.text, today=message.created_at.astimezone(KST).date())
            if request.route is Route.CHAT
            else None
        )
        if task_update is not None:
            await self._propose_task_due_update(message, task_update)
            return
        task_create = (
            parse_task_create(request.text, today=message.created_at.astimezone(KST).date())
            if request.route is Route.CHAT
            else None
        )
        if task_create is not None:
            await self._propose_task_create(message, task_create)
            return
        task_action = parse_task_action(request.text) if request.route is Route.CHAT else None
        if task_action is not None:
            await self._propose_task_action(message, task_action)
            return
        event_create = (
            parse_event_create(request.text, today=message.created_at.astimezone(KST).date())
            if request.route is Route.CHAT
            else None
        )
        if event_create is not None:
            await self._propose_event_create(message, event_create)
            return
        memo_edit = parse_memo_edit(request.text) if request.route is Route.CHAT else None
        if memo_edit is not None:
            await self._propose_memo_edit(message, memo_edit)
            return
        memo_delete = parse_memo_delete(request.text) if request.route is Route.CHAT else None
        if memo_delete is not None:
            await self._propose_memo_delete(message, memo_delete)
            return
        memo_create = parse_memo_create(request.text) if request.route is Route.CHAT else None
        if memo_create is not None:
            await self._propose_memo_create(message, memo_create)
            return
        view: discord.ui.View | None = None
        async with message.channel.typing():
            try:
                tool_request = (
                    parse_tool_request(request.text, today=message.created_at.astimezone(KST).date())
                    if request.route is Route.CHAT
                    else None
                )
                if tool_request is not None:
                    reply, view = await self._answer_with_governor_tool(request.text, tool_request, actor_id=int(message.author.id))
                elif request.route is Route.CHAT and self.settings.auto_route_enabled:
                    reply = await self.ollama.generate_auto(request.text)
                else:
                    reply = await self.ollama.generate(request.route, request.text)
            except OllamaError as exc:
                LOGGER.warning("Ollama failed route=%s: %s", request.route.value, exc)
                label = "Deep thinking failed" if request.route is Route.DEEP else "Brain failed"
                reply = f"{label}: {exc}"
        await message.reply(
            reply[: self.settings.max_reply_chars],
            view=view,
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _answer_with_governor_tool(
        self,
        user_text: str,
        tool_request: ToolRequest,
        *,
        actor_id: int,
    ) -> tuple[str, discord.ui.View | None]:
        if self.governor_tools is None:
            return "Governor tools are not configured yet.", None
        try:
            payload = await self.governor_tools.fetch(tool_request)
        except GovernorToolError as exc:
            return f"Governor tool failed: {exc}", None
        context = render_tool_context(tool_request, payload)
        if tool_request.kind is ToolKind.MEMO_SEARCH:
            results = search_results(payload)
            view = (
                BrainMemoSearchView(
                    self.governor_tools,
                    actor_id,
                    tool_request.query,
                    results,
                    memos_public_url=self.settings.memos_public_url,
                )
                if len(results) > 1
                else None
            )
            return context, view
        if tool_request.kind is ToolKind.DOCUMENT_SEARCH:
            results = search_results(payload)
            view = BrainDocumentSearchView(self.governor_tools, actor_id, tool_request.query, results) if len(results) > 1 else None
            return context, view
        if tool_request.kind is ToolKind.COMPLETED_TASKS:
            tasks = _task_results(payload)
            view = BrainCompletedTasksView(self.governor_tools, actor_id, tool_request, tasks) if tasks else None
            return context, view
        if tool_request.kind is ToolKind.ACTIVE_TASKS:
            tasks = _task_results(payload)
            view = BrainActiveTasksView(self.governor_tools, actor_id, tool_request, tasks) if tasks else None
            return context, view
        if tool_request.kind is ToolKind.TODAY:
            return context, None
        try:
            return await self.ollama.summarize_tool_result(user_text, context), None
        except OllamaError:
            return context, None

    async def _propose_task_due_update(self, message: discord.Message, request: TaskDueUpdateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                "Governor tools are not configured yet.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_task_due_update(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            await message.reply(
                f"Task edit proposal failed: {exc}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_task_due_update_proposal(payload),
            view=TaskUpdateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_task_create(self, message: discord.Message, request: TaskCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                "Governor tools are not configured yet.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_task_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            await message.reply(
                f"Task creation proposal failed: {exc}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_task_create_proposal(payload),
            view=TaskCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_task_action(self, message: discord.Message, request: TaskActionRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                "Governor tools are not configured yet.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_task_action(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            await message.reply(
                f"Task action proposal failed: {exc}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_task_action_proposal(payload),
            view=TaskActionConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_event_create(self, message: discord.Message, request: EventCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                "Governor tools are not configured yet.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_event_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            await message.reply(
                f"Event creation proposal failed: {exc}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_event_create_proposal(payload),
            view=EventCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_memo_create(self, message: discord.Message, request: MemoCreateRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                "Governor tools are not configured yet.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_memo_create(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            await message.reply(
                f"Memo creation proposal failed: {exc}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_memo_create_proposal(payload),
            view=MemoCreateConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_memo_delete(self, message: discord.Message, request: MemoDeleteRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                "Governor tools are not configured yet.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_memo_delete(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            await message.reply(
                f"Memo delete proposal failed: {exc}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_memo_delete_proposal(payload),
            view=MemoDeleteConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _propose_memo_edit(self, message: discord.Message, request: MemoEditRequest) -> None:
        if self.governor_tools is None:
            await message.reply(
                "Governor tools are not configured yet.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        try:
            payload = await self.governor_tools.propose_memo_edit(
                request,
                actor_id=message.author.id,
                idempotency_key=f"discord:{message.id}",
            )
        except GovernorToolError as exc:
            await message.reply(
                f"Memo edit proposal failed: {exc}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return
        await message.reply(
            render_memo_edit_proposal(payload),
            view=MemoEditConfirmationView(self.governor_tools, int(message.author.id), str(payload.get("confirmationId") or "")),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )


class BrainMemoSearchView(discord.ui.View):
    def __init__(
        self,
        governor_tools: GovernorToolClient,
        actor_id: int,
        query: str,
        results: list[dict[str, Any]],
        *,
        memos_public_url: str = "",
    ) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.results = results[:25]
        self.memos_public_url = memos_public_url
        self.add_item(BrainMemoSearchSelect(self))

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
        super().__init__(placeholder="Open memo", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_memo(str(item.get("name") or ""))
            memo = payload.get("memo")
            if isinstance(memo, dict):
                item = {**item, **memo, "full": True}
            content = render_memo_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            content = f"Memo open failed: {exc}"
            await interaction.response.send_message(content, ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        view = BrainOpenedMemoView(self.parent_view.governor_tools, self.parent_view.actor_id, str(item.get("name") or ""), content)
        await interaction.response.defer()
        await interaction.followup.send(content, view=view, allowed_mentions=NO_MENTIONS)


class BrainOpenedMemoView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

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
        await interaction.message.delete()

    @discord.ui.button(label="More...", style=discord.ButtonStyle.secondary)
    async def more(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoActionsView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainOpenedMemoActionsView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

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
        await interaction.message.delete()

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainMemoEditConfirmView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainMemoDeleteConfirmView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainMemoEditConfirmView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Edit Memo", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            BrainMemoEditModal(self.governor_tools, self.actor_id, self.name, self.content, interaction.message)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, self.content)
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
    ) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.source_message = source_message
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
            await interaction.response.send_message(f"Memo edit failed: {exc}", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if self.source_message is not None:
            view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, content)
            await interaction.response.defer(ephemeral=True)
            await self.source_message.edit(content=content[:1900], view=view, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.send_message(content[:1900], view=BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, content), ephemeral=True, allowed_mentions=NO_MENTIONS)


class BrainMemoDeleteConfirmView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, name: str, content: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.name = name
        self.content = content

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Delete Memo", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            proposal = await self.governor_tools.propose_memo_delete_by_name(
                self.name,
                actor_id=self.actor_id,
                idempotency_key=f"brain-memo-delete-{interaction.id}",
            )
            await self.governor_tools.approve_confirmation(str(proposal.get("confirmationId") or ""), actor_id=self.actor_id)
        except GovernorToolError as exc:
            await interaction.response.send_message(f"Memo delete failed: {exc}", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        deleted_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        view = BrainDeletedMemoView(self.governor_tools, self.actor_id, self.content)
        await interaction.response.edit_message(content=render_memo_deleted(self.content, deleted_at), view=view, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, self.name, self.content)
        await interaction.response.edit_message(view=view, allowed_mentions=NO_MENTIONS)
        self.stop()


class BrainDeletedMemoView(discord.ui.View):
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
            await interaction.response.send_message(f"Memo restore failed: {exc}", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        view = BrainOpenedMemoView(self.governor_tools, self.actor_id, name, content)
        await interaction.response.edit_message(content=content[:1900], view=view, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Delete this Message", style=discord.ButtonStyle.danger)
    async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Message delete failed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.message.delete()


class BrainDocumentSearchView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, query: str, results: list[dict[str, Any]]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.query = query
        self.results = results[:25]
        self.add_item(BrainDocumentSearchSelect(self))

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
        super().__init__(placeholder="Open document", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            item = self.parent_view.results[int(self.values[0])]
            payload = await self.parent_view.governor_tools.get_document(item.get("id"))
            document = payload.get("document")
            if isinstance(document, dict):
                item = {**item, **document, "full": True}
            content = render_document_opened(self.parent_view.query, item)
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            content = f"Document open failed: {exc}"
        await interaction.response.defer()
        await interaction.followup.send(content, allowed_mentions=NO_MENTIONS)
        self.parent_view.stop()


class BrainCompletedTasksView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, tasks: list[dict[str, Any]]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.tasks = tasks[:25]
        self.add_item(BrainCompletedTasksSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainCompletedTasksSelect(discord.ui.Select):
    def __init__(self, parent: BrainCompletedTasksView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(task) or None,
                value=str(index),
            )
            for index, task in enumerate(parent.tasks)
        ]
        super().__init__(placeholder="Reopen completed item", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            task = self.parent_view.tasks[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
            payload = await self.parent_view.governor_tools.propose_task_action(
                TaskActionRequest(
                    title,
                    "reopen",
                    profile=self.parent_view.request.profile,
                    collection_id=self.parent_view.request.collection_id,
                ),
                actor_id=self.parent_view.actor_id,
                idempotency_key=f"brain-task-reopen-{interaction.id}",
            )
        except (GovernorToolError, IndexError, TypeError, ValueError) as exc:
            await interaction.response.send_message(f"Task reopen failed: {exc}", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.followup.send(
            render_task_action_proposal(payload),
            view=TaskActionConfirmationView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                str(payload.get("confirmationId") or ""),
            ),
            allowed_mentions=NO_MENTIONS,
        )


class BrainActiveTasksView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, tasks: list[dict[str, Any]]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.tasks = tasks[:25]
        self.add_item(BrainActiveTasksSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False


class BrainActiveTasksSelect(discord.ui.Select):
    def __init__(self, parent: BrainActiveTasksView) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=_task_option_label(task),
                description=_task_option_description(task) or None,
                value=str(index),
            )
            for index, task in enumerate(parent.tasks)
        ]
        super().__init__(placeholder="Choose active item", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            task = self.parent_view.tasks[int(self.values[0])]
            title = str(task.get("title") or task.get("summary") or "").strip()
            if not title:
                raise ValueError("missing task title")
        except (IndexError, TypeError, ValueError) as exc:
            await interaction.response.send_message(f"Task selection failed: {exc}", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.defer()
        await interaction.followup.send(
            f"## {title}",
            view=BrainActiveTaskActionsView(
                self.parent_view.governor_tools,
                self.parent_view.actor_id,
                self.parent_view.request,
                task,
            ),
            allowed_mentions=NO_MENTIONS,
        )


class BrainActiveTaskActionsView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, task: dict[str, Any]) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.task = task
        self.title = str(task.get("title") or task.get("summary") or "").strip()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._propose(interaction, "complete")

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BrainTaskEditModal(self.governor_tools, self.actor_id, self.request, self.task))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._propose(interaction, "delete")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.message is None:
            await interaction.response.send_message("Closed.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.message.delete()

    async def _propose(self, interaction: discord.Interaction, action: str) -> None:
        try:
            payload = await self.governor_tools.propose_task_action(
                TaskActionRequest(
                    self.title,
                    action,
                    profile=self.request.profile,
                    collection_id=self.request.collection_id,
                ),
                actor_id=self.actor_id,
                idempotency_key=f"brain-task-{action}-{interaction.id}",
            )
        except GovernorToolError as exc:
            await interaction.response.send_message(f"Task {action} failed: {exc}", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.edit_message(
            content=render_task_action_proposal(payload),
            view=TaskActionConfirmationView(self.governor_tools, self.actor_id, str(payload.get("confirmationId") or "")),
            allowed_mentions=NO_MENTIONS,
        )
        self.stop()


class BrainTaskEditModal(discord.ui.Modal):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, request: ToolRequest, task: dict[str, Any]) -> None:
        super().__init__(title="Edit Supply" if _uses_supplies_request(request) else "Edit Task", timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.request = request
        self.task = task
        self.title_input = discord.ui.TextInput(
            label="Title",
            style=discord.TextStyle.short,
            required=True,
            default=str(task.get("title") or task.get("summary") or "")[:100],
            max_length=100,
        )
        self.memo_input = discord.ui.TextInput(
            label="Memo",
            style=discord.TextStyle.paragraph,
            required=False,
            default=str(task.get("memo") or task.get("description") or "")[:1000],
            max_length=1000,
        )
        self.add_item(self.title_input)
        self.add_item(self.memo_input)
        if not _uses_supplies_request(request):
            self.due_date_input = discord.ui.TextInput(
                label="Due date",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("due") or "")[:10],
                placeholder="yyyy-mm-dd",
                max_length=10,
            )
            self.due_time_input = discord.ui.TextInput(
                label="Due time",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("dueTime") or "")[:5],
                placeholder="HH:MM",
                max_length=5,
            )
            self.priority_input = discord.ui.TextInput(
                label="Priority",
                style=discord.TextStyle.short,
                required=False,
                default=str(task.get("priority") or "")[:1],
                placeholder="blank, 1, 5, or 9",
                max_length=1,
            )
            self.add_item(self.due_date_input)
            self.add_item(self.due_time_input)
            self.add_item(self.priority_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        old_title = str(self.task.get("title") or self.task.get("summary") or "").strip()
        due_date = str(getattr(self, "due_date_input", _EmptyInput()).value or "")
        due_time = str(getattr(self, "due_time_input", _EmptyInput()).value or "")
        priority = str(getattr(self, "priority_input", _EmptyInput()).value or "")
        try:
            payload = await self.governor_tools.propose_task_edit(
                TaskEditRequest(
                    old_title,
                    str(self.title_input.value or ""),
                    str(self.memo_input.value or ""),
                    due_date=due_date,
                    due_time=due_time,
                    priority=priority,
                    profile=self.request.profile,
                    collection_id=self.request.collection_id,
                    uid=str(self.task.get("uid") or ""),
                ),
                actor_id=self.actor_id,
                idempotency_key=f"brain-task-edit-{interaction.id}",
            )
        except GovernorToolError as exc:
            await interaction.response.send_message(f"Task edit failed: {exc}", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await interaction.response.send_message(
            render_task_edit_proposal(payload),
            view=TaskEditConfirmationView(self.governor_tools, self.actor_id, str(payload.get("confirmationId") or "")),
            allowed_mentions=NO_MENTIONS,
        )


class _EmptyInput:
    value = ""


class TaskEditConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_edit_completed(payload)
        except GovernorToolError as exc:
            content = f"Task edit failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Task edit cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class TaskUpdateConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_due_update_completed(payload)
        except GovernorToolError as exc:
            content = f"Task edit failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Task edit cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class TaskCreateConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_create_completed(payload)
        except GovernorToolError as exc:
            content = f"Task creation failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Task creation cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class EventCreateConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_event_create_completed(payload)
        except GovernorToolError as exc:
            content = f"Event creation failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Event creation cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class TaskActionConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_task_action_completed(payload)
        except GovernorToolError as exc:
            content = f"Task action failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Task action cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class MemoCreateConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_memo_create_completed(payload)
        except GovernorToolError as exc:
            content = f"Memo creation failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Memo creation cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class MemoDeleteConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_memo_delete_completed(payload)
        except GovernorToolError as exc:
            content = f"Memo delete failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Memo delete cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


class MemoEditConfirmationView(discord.ui.View):
    def __init__(self, governor_tools: GovernorToolClient, actor_id: int, confirmation_id: str) -> None:
        super().__init__(timeout=600)
        self.governor_tools = governor_tools
        self.actor_id = actor_id
        self.confirmation_id = confirmation_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.actor_id:
            return True
        await interaction.response.send_message("Access denied.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            payload = await self.governor_tools.approve_confirmation(self.confirmation_id, actor_id=self.actor_id)
            content = render_memo_edit_completed(payload)
        except GovernorToolError as exc:
            content = f"Memo edit failed: {exc}"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=content, view=self, allowed_mentions=NO_MENTIONS)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Memo edit cancelled.", view=self, allowed_mentions=NO_MENTIONS)
        self.stop()


def _task_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tasks")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _uses_supplies_request(request: ToolRequest) -> bool:
    return request.profile == "supplies" or "supplies" in request.collection_id.lower()


def _task_option_label(task: dict[str, Any]) -> str:
    return _compact_select_text(str(task.get("title") or task.get("summary") or "Untitled task"), 100)


def _task_option_description(task: dict[str, Any]) -> str:
    completed = str(task.get("completedDate") or task.get("completed") or task.get("completedAt") or "").strip()[:10]
    due = str(task.get("due") or task.get("dueDate") or "").strip()
    parts = [part for part in (completed, due) if part]
    return _compact_select_text(" · ".join(parts), 100)


def _compact_select_text(value: str, limit: int) -> str:
    text = " ".join(value.split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
