from __future__ import annotations

from abc import ABC, abstractmethod

from dizzybot.domain import RadioStation, ResolveResult


class BaseRadioRepository(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    async def add(self, station: RadioStation) -> RadioStation: ...

    @abstractmethod
    async def get(self, guild_id: int, name: str) -> RadioStation | None: ...

    @abstractmethod
    async def list(self, guild_id: int) -> tuple[RadioStation, ...]: ...

    @abstractmethod
    async def remove(self, guild_id: int, name: str) -> RadioStation | None: ...


class BaseRadioResolver(ABC):
    @abstractmethod
    async def validate_url(self, url: str) -> str: ...

    @abstractmethod
    async def resolve(self, station: RadioStation, requester_id: int) -> ResolveResult: ...
