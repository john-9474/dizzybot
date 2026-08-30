from __future__ import annotations

from abc import ABC, abstractmethod

from dizzybot.contracts.player import BaseGuildPlayer
from dizzybot.domain import QueueSnapshot


class BasePlaybackControls(ABC):
    @abstractmethod
    def bind_player(self, player: BaseGuildPlayer) -> None: ...

    @abstractmethod
    async def update(
        self,
        guild_id: int,
        channel_id: int,
        snapshot: QueueSnapshot,
    ) -> None: ...

    @abstractmethod
    async def clear(self, guild_id: int) -> None: ...
