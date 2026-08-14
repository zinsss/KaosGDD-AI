from __future__ import annotations

import logging

import discord

from .config import Settings
from .intent import Route, parse_request
from .ollama import OllamaClient, OllamaConfig, OllamaError

LOGGER = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()


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
        async with message.channel.typing():
            try:
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
