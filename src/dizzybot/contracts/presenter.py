from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from dizzybot.domain import QueueSnapshot, Track


class BasePresenter(ABC):
    @abstractmethod
    def attach(self, client: Any) -> None: ...

    @abstractmethod
    async def respond(
        self,
        interaction: Any,
        title: str,
        description: str,
        *,
        error: bool = False,
        ephemeral: bool = False,
    ) -> None: ...

    @abstractmethod
    async def notify(
        self,
        channel_id: int,
        title: str,
        description: str,
        *,
        error: bool = False,
    ) -> None: ...

    @abstractmethod
    def now_playing_embed(self, snapshot: QueueSnapshot) -> Any: ...

    @abstractmethod
    async def respond_now_playing(self, interaction: Any, snapshot: QueueSnapshot) -> None: ...

    @abstractmethod
    def track_description(self, track: Track) -> str: ...

    @abstractmethod
    def queue_page(self, snapshot: QueueSnapshot, page: int) -> tuple[str, str]: ...
