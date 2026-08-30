from __future__ import annotations

import random

from dizzybot.contracts import BaseQueue
from dizzybot.domain import PlaybackEndReason, RepeatMode, Track
from dizzybot.errors import InvalidRequestError


class DefaultQueue(BaseQueue):
    HISTORY_LIMIT = 500

    def __init__(self) -> None:
        self._current: Track | None = None
        self._upcoming: list[Track] = []
        self._history: list[Track] = []
        self._repeat_mode = RepeatMode.OFF
        self._current_position = 0
        self._total_size = 0

    @property
    def current(self) -> Track | None:
        return self._current

    @property
    def repeat_mode(self) -> RepeatMode:
        return self._repeat_mode

    @property
    def current_position(self) -> int | None:
        return self._current_position if self._current is not None else None

    @property
    def total_size(self) -> int:
        return self._total_size

    @property
    def can_go_previous(self) -> bool:
        return self._current is not None and bool(self._history)

    def set_repeat_mode(self, mode: RepeatMode) -> None:
        self._repeat_mode = mode

    def enqueue(self, tracks: tuple[Track, ...]) -> None:
        if self._current is None and not self._upcoming:
            self._history.clear()
            self._current_position = 0
            self._total_size = 0
        self._upcoming.extend(tracks)
        self._total_size += len(tracks)

    def take_next(self) -> Track | None:
        if self._current is not None:
            return self._current
        if not self._upcoming:
            self._history.clear()
            self._current_position = 0
            self._total_size = 0
            return None
        self._current = self._upcoming.pop(0)
        if self._current_position == 0:
            self._current_position = 1
        return self._current

    def take_previous(self) -> Track:
        if self._current is None or not self._history:
            raise InvalidRequestError("There is no previous track in this playback session.")
        interrupted = self._current
        previous = self._history.pop()
        self._upcoming.insert(0, interrupted)
        if self._repeat_mode is RepeatMode.QUEUE:
            for index in range(len(self._upcoming) - 1, 0, -1):
                candidate = self._upcoming[index]
                same_track = (
                    candidate.backend_key == previous.backend_key
                    if previous.backend_key
                    else (
                        candidate.identifier == previous.identifier
                        and candidate.source is previous.source
                    )
                )
                if same_track:
                    self._upcoming.pop(index)
                    break
            self._current_position = (
                self._total_size if self._current_position <= 1 else self._current_position - 1
            )
        else:
            self._current_position = max(1, self._current_position - 1)
        self._current = previous
        return previous

    def complete_current(self, reason: PlaybackEndReason) -> None:
        completed = self._current
        self._current = None
        if completed is None:
            return
        if reason in {PlaybackEndReason.LOAD_FAILED, PlaybackEndReason.STUCK}:
            self._total_size = max(0, self._total_size - 1)
            return
        if reason is PlaybackEndReason.FINISHED and self._repeat_mode is RepeatMode.TRACK:
            self._upcoming.insert(0, completed)
            return

        self._history.append(completed)
        if len(self._history) > self.HISTORY_LIMIT:
            self._history.pop(0)
        if reason is PlaybackEndReason.FINISHED and self._repeat_mode is RepeatMode.QUEUE:
            self._upcoming.append(completed)
            if self._total_size:
                self._current_position = self._current_position % self._total_size + 1
        elif self._upcoming:
            self._current_position += 1

    def upcoming(self) -> tuple[Track, ...]:
        return tuple(self._upcoming)

    def remove(self, position: int) -> Track:
        index = position - 1
        if index < 0 or index >= len(self._upcoming):
            raise InvalidRequestError("Queue position is out of range.")
        track = self._upcoming.pop(index)
        self._total_size = max(self._current_position, self._total_size - 1)
        return track

    def move(self, from_position: int, to_position: int) -> Track:
        from_index = from_position - 1
        to_index = to_position - 1
        if from_index < 0 or from_index >= len(self._upcoming):
            raise InvalidRequestError("Source queue position is out of range.")
        if to_index < 0 or to_index >= len(self._upcoming):
            raise InvalidRequestError("Destination queue position is out of range.")
        track = self._upcoming.pop(from_index)
        self._upcoming.insert(to_index, track)
        return track

    def clear_upcoming(self) -> int:
        count = len(self._upcoming)
        self._upcoming.clear()
        self._total_size = self._current_position if self._current is not None else 0
        return count

    def stop(self) -> None:
        self._current = None
        self._upcoming.clear()
        self._history.clear()
        self._current_position = 0
        self._total_size = 0

    def reset(self) -> None:
        self.stop()
        self._repeat_mode = RepeatMode.OFF

    def shuffle(self) -> None:
        random.shuffle(self._upcoming)
