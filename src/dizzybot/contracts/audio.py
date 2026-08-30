from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from dizzybot.domain import BackendLoadResult, PlaybackEndReason, Track

AudioEventHandler = Callable[[int, PlaybackEndReason, str | None], Awaitable[None]]


class BaseAudioBackend(ABC):
    @abstractmethod
    def set_event_handler(self, handler: AudioEventHandler) -> None: ...

    @abstractmethod
    async def start(self, client: Any) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    async def load_tracks(self, identifier: str) -> BackendLoadResult: ...

    @abstractmethod
    async def connect(self, guild_id: int, channel: Any) -> None: ...

    @abstractmethod
    async def disconnect(self, guild_id: int) -> None: ...

    @abstractmethod
    async def play(self, guild_id: int, track: Track, volume: int) -> None: ...

    @abstractmethod
    async def stop(self, guild_id: int) -> None: ...

    @abstractmethod
    async def pause(self, guild_id: int, paused: bool) -> None: ...

    @abstractmethod
    async def seek(self, guild_id: int, position_ms: int) -> None: ...

    @abstractmethod
    async def set_volume(self, guild_id: int, volume: int) -> None: ...

    @abstractmethod
    def is_connected(self, guild_id: int) -> bool: ...

    @abstractmethod
    def channel_id(self, guild_id: int) -> int | None: ...

    @abstractmethod
    def position_ms(self, guild_id: int) -> int: ...

    @abstractmethod
    def is_paused(self, guild_id: int) -> bool: ...
