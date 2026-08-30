from dataclasses import dataclass


@dataclass(frozen=True)
class AccessPolicy:
    guild_id: int
    allowed_user_ids: frozenset[int]
    allowed_channel_ids: frozenset[int]

    def allows(self, guild_id: int | None, channel_id: int | None, user_id: int) -> bool:
        return guild_id == self.guild_id and channel_id in self.allowed_channel_ids and user_id in self.allowed_user_ids
