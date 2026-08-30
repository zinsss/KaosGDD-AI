from __future__ import annotations

from dataclasses import dataclass

import discord

DISCORD_MESSAGE_LIMIT = 2_000
NO_MENTIONS = discord.AllowedMentions.none()


class MarkdownMessageTooLong(ValueError):
    """Raised instead of silently truncating a Discord message."""


def escape_text(value: object) -> str:
    """Escape dynamic text while leaving renderer-owned Markdown intact."""
    text = discord.utils.escape_mentions(str(value))
    return discord.utils.escape_markdown(text, as_needed=True)


@dataclass(frozen=True)
class MarkdownField:
    label: str
    value: object


@dataclass(frozen=True)
class MarkdownMessage:
    title: str
    summary: str | None = None
    fields: tuple[MarkdownField, ...] = ()
    bullets: tuple[str, ...] = ()
    quote: str | None = None
    footer: str | None = None

    def render(self) -> str:
        sections = [f"## {escape_text(self.title)}"]
        if self.summary:
            sections.append(escape_text(self.summary))
        sections.extend(
            f"**{escape_text(field.label)}**\n{escape_text(field.value)}"
            for field in self.fields
        )
        if self.bullets:
            sections.append("\n".join(f"- {escape_text(item)}" for item in self.bullets))
        if self.quote:
            sections.append("\n".join(f"> {escape_text(line)}" for line in self.quote.splitlines()))
        if self.footer:
            sections.append(f"-# {escape_text(self.footer)}")

        content = "\n\n".join(sections)
        if len(content) > DISCORD_MESSAGE_LIMIT:
            raise MarkdownMessageTooLong(
                f"Discord message is {len(content)} characters; maximum is {DISCORD_MESSAGE_LIMIT}"
            )
        return content
