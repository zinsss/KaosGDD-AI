from __future__ import annotations

import asyncio
import logging

import discord
from kaos_governor.memos import MemosError, MemosService

from .access import AccessPolicy
from .markdown import NO_MENTIONS


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
        try:
            memo = await asyncio.to_thread(self.service.create, content)
        except (ValueError, MemosError) as exc:
            self.rejected_count += 1
            self.last_error = exc.code if isinstance(exc, MemosError) else str(exc)
            await message.reply(
                f"Memos rejected: {self.last_error}",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return True
        except Exception as exc:
            self.rejected_count += 1
            self.last_error = type(exc).__name__
            LOGGER.exception("Unexpected Memos capture failure")
            await message.reply("Memos rejected: internal_error", mention_author=False, allowed_mentions=NO_MENTIONS)
            return True
        await self._delete_message(message)
        await message.channel.send(
            f"Saved to Memos: {memo.name}",
            delete_after=self.confirmation_delete_after,
            allowed_mentions=NO_MENTIONS,
        )
        self.accepted_count += 1
        self.last_error = ""
        return True

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "channelId": str(self.channel_id),
            "acceptedCount": self.accepted_count,
            "rejectedCount": self.rejected_count,
            "lastError": self.last_error,
        }

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            LOGGER.info("Could not delete captured Memos message %s", getattr(message, "id", ""))
