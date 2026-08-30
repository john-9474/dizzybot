from abc import ABC, abstractmethod

from dizzybot.domain import ResolveRequest, ResolveResult, Source


class BaseTrackResolver(ABC):
    @abstractmethod
    def detect_source(self, query: str) -> Source | None: ...

    @abstractmethod
    async def resolve(self, request: ResolveRequest) -> ResolveResult: ...
