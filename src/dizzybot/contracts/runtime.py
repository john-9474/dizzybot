from abc import ABC, abstractmethod


class BaseBotRuntime(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
