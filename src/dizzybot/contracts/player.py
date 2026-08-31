from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from dizzybot.domain import (
    GuildSettings,
    PlaybackEndReason,
    QueueSnapshot,
    RepeatMode,
    ResolveResult,
    Track,
)


class BaseGuildPlayer(ABC):
    guild_id: int

    @abstractmethod
    async def connect(self, channel: Any, announce_channel_id: int) -> None: ...

    @abstractmethod
    async def enqueue(self, result: ResolveResult, announce_channel_id: int) -> int: ...

    @abstractmethod
    async def leave(self) -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def resume(self) -> None: ...

    @abstractmethod
    async def skip(self) -> Track: ...

    @abstractmethod
    async def previous(self) -> Track: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def remove(self, position: int) -> Track: ...

    @abstractmethod
    async def move(self, from_position: int, to_position: int) -> Track: ...

    @abstractmethod
    async def clear(self) -> int: ...

    @abstractmethod
    async def shuffle(self) -> None: ...

    @abstractmethod
    async def set_repeat(self, mode: RepeatMode) -> None: ...

    @abstractmethod
    async def set_volume(self, volume: int) -> None: ...

    @abstractmethod
    async def seek(self, position_ms: int) -> None: ...

    @abstractmethod
    async def snapshot(self) -> QueueSnapshot: ...

    @abstractmethod
    async def repost_controls(self) -> None: ...

    @abstractmethod
    async def handle_track_end(
        self, reason: PlaybackEndReason, backend_key: str | None
    ) -> None: ...

    @abstractmethod
    async def update_human_presence(self, has_humans: bool) -> None: ...

    @abstractmethod
    def channel_id(self) -> int | None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    async def update_settings(self, settings: GuildSettings) -> None: ...


class BasePlayerManager(ABC):
    @abstractmethod
    async def get_or_create(self, guild_id: int) -> BaseGuildPlayer: ...

    @abstractmethod
    def get(self, guild_id: int) -> BaseGuildPlayer | None: ...

    @abstractmethod
    async def repost_controls(self, guild_id: int) -> None: ...

    @abstractmethod
    async def handle_track_end(
        self, guild_id: int, reason: PlaybackEndReason, backend_key: str | None
    ) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
