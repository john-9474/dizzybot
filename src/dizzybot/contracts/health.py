from abc import ABC, abstractmethod

from dizzybot.domain import HealthSnapshot


class BaseHealthService(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def snapshot(self) -> HealthSnapshot: ...
