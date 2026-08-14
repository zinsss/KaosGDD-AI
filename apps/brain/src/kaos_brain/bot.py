from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

import discord

from .config import Settings
from .governor_tools import (
    GovernorToolClient,
    GovernorToolConfig,
    GovernorToolError,
    render_task_create_completed,
    render_task_create_proposal,
    render_task_due_update_completed,
    render_task_due_update_proposal,
    render_tool_context,
)
from .intent import Route, parse_request
from .ollama import OllamaClient, OllamaConfig, OllamaError
from .task_update_intent import TaskCreateRequest, TaskDueUpdateRequest, parse_task_create, parse_task_due_update
from .tool_intent import ToolRequest, parse_tool_request

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
        async with message.channel.typing():
            try:
                tool_request = parse_tool_request(request.text) if request.route is Route.CHAT else None
                if tool_request is not None:
                    reply = await self._answer_with_governor_tool(request.text, tool_request)
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
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    async def _answer_with_governor_tool(self, user_text: str, tool_request: ToolRequest) -> str:
        if self.governor_tools is None:
            return "Governor tools are not configured yet."
        try:
            payload = await self.governor_tools.fetch(tool_request)
        except GovernorToolError as exc:
            return f"Governor tool failed: {exc}"
        context = render_tool_context(tool_request, payload)
        try:
            return await self.ollama.summarize_tool_result(user_text, context)
        except OllamaError:
            return context

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
