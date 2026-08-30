from abc import ABC, abstractmethod

from dizzybot.domain import PlaybackEndReason, RepeatMode, Track


class BaseQueue(ABC):
    @property
    @abstractmethod
    def current(self) -> Track | None: ...

    @property
    @abstractmethod
    def repeat_mode(self) -> RepeatMode: ...

    @property
    @abstractmethod
    def current_position(self) -> int | None: ...

    @property
    @abstractmethod
    def total_size(self) -> int: ...

    @property
    @abstractmethod
    def can_go_previous(self) -> bool: ...

    @abstractmethod
    def set_repeat_mode(self, mode: RepeatMode) -> None: ...

    @abstractmethod
    def enqueue(self, tracks: tuple[Track, ...]) -> None: ...

    @abstractmethod
    def take_next(self) -> Track | None: ...

    @abstractmethod
    def take_previous(self) -> Track: ...

    @abstractmethod
    def complete_current(self, reason: PlaybackEndReason) -> None: ...

    @abstractmethod
    def upcoming(self) -> tuple[Track, ...]: ...

    @abstractmethod
    def remove(self, position: int) -> Track: ...

    @abstractmethod
    def move(self, from_position: int, to_position: int) -> Track: ...

    @abstractmethod
    def clear_upcoming(self) -> int: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def shuffle(self) -> None: ...
