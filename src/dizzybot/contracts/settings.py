from abc import ABC, abstractmethod

from dizzybot.domain import GuildSettings


class BaseSettingsRepository(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    async def get(self, guild_id: int) -> GuildSettings: ...

    @abstractmethod
    async def save(self, settings: GuildSettings) -> GuildSettings: ...

    @abstractmethod
    async def reset(self, guild_id: int) -> GuildSettings: ...
