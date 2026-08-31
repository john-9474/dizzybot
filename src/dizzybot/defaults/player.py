from __future__ import annotations

import asyncio
import contextlib
from collections import Counter
from collections.abc import Callable
from typing import Any

from dizzybot.contracts import (
    BaseAudioBackend,
    BaseGuildPlayer,
    BasePlaybackControls,
    BasePlayerManager,
    BasePresenter,
    BaseQueue,
    BaseSettingsRepository,
)
from dizzybot.domain import (
    GuildSettings,
    PlaybackEndReason,
    QueueSnapshot,
    RepeatMode,
    ResolveResult,
    Track,
)
from dizzybot.errors import InvalidRequestError, PlayerStateError, QueueLimitError

GuildPlayerFactory = Callable[..., BaseGuildPlayer]
QueueFactory = Callable[[], BaseQueue]


class DefaultGuildPlayer(BaseGuildPlayer):
    def __init__(
        self,
        guild_id: int,
        backend: BaseAudioBackend,
        queue: BaseQueue,
        presenter: BasePresenter,
        controls: BasePlaybackControls,
        settings: GuildSettings,
        *,
        queue_limit: int,
    ) -> None:
        self.guild_id = guild_id
        self._backend = backend
        self._queue = queue
        self._presenter = presenter
        self._controls = controls
        self._settings = settings
        self._queue_limit = queue_limit
        self._volume = settings.default_volume
        self._announce_channel_id: int | None = None
        self._has_humans = True
        self._idle_task: asyncio.Task[None] | None = None
        self._ignored_end_events: Counter[str] = Counter()
        self._lock = asyncio.Lock()

    async def connect(self, channel: Any, announce_channel_id: int) -> None:
        async with self._lock:
            await self._backend.connect(self.guild_id, channel)
            self._announce_channel_id = announce_channel_id
            # Player instances survive voice disconnects. Re-establish presence from
            # the newly joined channel so an empty-channel state from the previous
            # session cannot disconnect active playback after the idle timeout.
            members = getattr(channel, "members", None)
            self._has_humans = (
                True
                if members is None
                else any(not getattr(member, "bot", False) for member in members)
            )
            await self._backend.set_volume(self.guild_id, self._volume)
            self._refresh_idle_timer_locked()

    async def enqueue(self, result: ResolveResult, announce_channel_id: int) -> int:
        async with self._lock:
            if not self._backend.is_connected(self.guild_id):
                raise PlayerStateError("The bot is not connected to a voice channel.")
            occupied = len(self._queue.upcoming()) + (1 if self._queue.current else 0)
            if occupied + len(result.tracks) > self._queue_limit:
                raise QueueLimitError(
                    f"This would exceed the server queue limit of {self._queue_limit} tracks."
                )
            self._announce_channel_id = announce_channel_id
            self._queue.enqueue(result.tracks)
            await self._play_next_locked()
            return len(result.tracks)

    async def _play_next_locked(self) -> None:
        while self._queue.current is None:
            track = self._queue.take_next()
            if track is None:
                self._refresh_idle_timer_locked()
                await self._controls.clear(self.guild_id)
                return
            try:
                await self._backend.play(self.guild_id, track, self._volume)
            except Exception:
                self._queue.complete_current(PlaybackEndReason.LOAD_FAILED)
                if self._announce_channel_id is not None:
                    await self._presenter.notify(
                        self._announce_channel_id,
                        "Track failed",
                        f"Could not play **{track.title}**; continuing with the queue.",
                        error=True,
                    )
                continue
        self._refresh_idle_timer_locked()
        await self._update_controls_locked()

    def _snapshot_locked(self) -> QueueSnapshot:
        return QueueSnapshot(
            current=self._queue.current,
            upcoming=self._queue.upcoming(),
            repeat_mode=self._queue.repeat_mode,
            volume=self._volume,
            paused=self._backend.is_paused(self.guild_id),
            position_ms=self._backend.position_ms(self.guild_id),
            queue_position=self._queue.current_position,
            queue_total=self._queue.total_size,
            can_go_previous=self._queue.can_go_previous,
        )

    async def _update_controls_locked(self) -> None:
        if self._announce_channel_id is None:
            return
        await self._controls.update(
            self.guild_id,
            self._announce_channel_id,
            self._snapshot_locked(),
        )

    def _ignore_current_end_locked(self) -> None:
        current = self._queue.current
        if current is not None and current.backend_key:
            self._ignored_end_events[current.backend_key] += 1

    async def leave(self) -> None:
        async with self._lock:
            self._cancel_idle_timer_locked()
            self._ignore_current_end_locked()
            self._queue.reset()
            if self._backend.is_connected(self.guild_id):
                await self._backend.disconnect(self.guild_id)
            self._announce_channel_id = None
            await self._controls.clear(self.guild_id)

    def _require_current(self) -> Track:
        track = self._queue.current
        if track is None:
            raise PlayerStateError("Nothing is currently playing.")
        return track

    async def pause(self) -> None:
        async with self._lock:
            self._require_current()
            if self._backend.is_paused(self.guild_id):
                raise PlayerStateError("Playback is already paused.")
            await self._backend.pause(self.guild_id, True)
            await self._update_controls_locked()

    async def resume(self) -> None:
        async with self._lock:
            self._require_current()
            if not self._backend.is_paused(self.guild_id):
                raise PlayerStateError("Playback is not paused.")
            await self._backend.pause(self.guild_id, False)
            await self._update_controls_locked()

    async def skip(self) -> Track:
        async with self._lock:
            track = self._require_current()
            self._ignore_current_end_locked()
            self._queue.complete_current(PlaybackEndReason.SKIPPED)
            await self._backend.stop(self.guild_id)
            await self._play_next_locked()
            return track

    async def previous(self) -> Track:
        async with self._lock:
            interrupted = self._require_current()
            track = self._queue.take_previous()
            if interrupted.backend_key:
                self._ignored_end_events[interrupted.backend_key] += 1
            await self._backend.stop(self.guild_id)
            try:
                await self._backend.play(self.guild_id, track, self._volume)
            except Exception:
                self._queue.complete_current(PlaybackEndReason.LOAD_FAILED)
                if self._announce_channel_id is not None:
                    await self._presenter.notify(
                        self._announce_channel_id,
                        "Track failed",
                        f"Could not replay **{track.title}**; continuing with the queue.",
                        error=True,
                    )
                await self._play_next_locked()
            else:
                await self._update_controls_locked()
            return track

    async def stop(self) -> None:
        async with self._lock:
            self._require_current()
            self._ignore_current_end_locked()
            self._queue.stop()
            await self._backend.stop(self.guild_id)
            self._refresh_idle_timer_locked()
            await self._controls.clear(self.guild_id)

    async def remove(self, position: int) -> Track:
        async with self._lock:
            track = self._queue.remove(position)
            await self._update_controls_locked()
            return track

    async def move(self, from_position: int, to_position: int) -> Track:
        async with self._lock:
            track = self._queue.move(from_position, to_position)
            await self._update_controls_locked()
            return track

    async def clear(self) -> int:
        async with self._lock:
            count = self._queue.clear_upcoming()
            await self._update_controls_locked()
            return count

    async def shuffle(self) -> None:
        async with self._lock:
            if len(self._queue.upcoming()) < 2:
                raise PlayerStateError("At least two queued tracks are needed to shuffle.")
            self._queue.shuffle()
            await self._update_controls_locked()

    async def set_repeat(self, mode: RepeatMode) -> None:
        async with self._lock:
            self._queue.set_repeat_mode(mode)
            await self._update_controls_locked()

    async def set_volume(self, volume: int) -> None:
        if not 0 <= volume <= 100:
            raise InvalidRequestError("Volume must be between 0 and 100.")
        async with self._lock:
            if not self._backend.is_connected(self.guild_id):
                raise PlayerStateError()
            self._volume = volume
            await self._backend.set_volume(self.guild_id, volume)
            await self._update_controls_locked()

    async def seek(self, position_ms: int) -> None:
        async with self._lock:
            track = self._require_current()
            if not track.is_seekable or track.is_stream:
                raise PlayerStateError("That track cannot be seeked.")
            if position_ms < 0 or (
                track.duration_ms is not None and position_ms >= track.duration_ms
            ):
                raise InvalidRequestError("Seek position is outside the track duration.")
            await self._backend.seek(self.guild_id, position_ms)
            await self._update_controls_locked()

    async def snapshot(self) -> QueueSnapshot:
        async with self._lock:
            return self._snapshot_locked()

    async def handle_track_end(self, reason: PlaybackEndReason, backend_key: str | None) -> None:
        async with self._lock:
            if backend_key and self._ignored_end_events[backend_key]:
                self._ignored_end_events[backend_key] -= 1
                if not self._ignored_end_events[backend_key]:
                    del self._ignored_end_events[backend_key]
                return
            current = self._queue.current
            if current is None:
                return
            if backend_key and current.backend_key and backend_key != current.backend_key:
                return
            failed = reason in {PlaybackEndReason.LOAD_FAILED, PlaybackEndReason.STUCK}
            self._queue.complete_current(reason)
            if failed and self._announce_channel_id is not None:
                await self._presenter.notify(
                    self._announce_channel_id,
                    "Playback error",
                    f"**{current.title}** failed; continuing with the queue.",
                    error=True,
                )
            await self._play_next_locked()

    async def update_human_presence(self, has_humans: bool) -> None:
        async with self._lock:
            self._has_humans = has_humans
            self._refresh_idle_timer_locked()

    def channel_id(self) -> int | None:
        return self._backend.channel_id(self.guild_id)

    def is_connected(self) -> bool:
        return self._backend.is_connected(self.guild_id)

    async def update_settings(self, settings: GuildSettings) -> None:
        async with self._lock:
            timeout_changed = settings.idle_timeout_seconds != self._settings.idle_timeout_seconds
            self._settings = settings
            if timeout_changed:
                self._cancel_idle_timer_locked()
            self._refresh_idle_timer_locked()
            await self._update_controls_locked()

    def _should_idle_disconnect(self) -> bool:
        return (
            not self._settings.stay_connected
            and self.is_connected()
            and (self._queue.current is None or not self._has_humans)
        )

    def _refresh_idle_timer_locked(self) -> None:
        if not self._should_idle_disconnect():
            self._cancel_idle_timer_locked()
        elif self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.create_task(
                self._idle_disconnect_after_delay(),
                name=f"dizzybot-idle-{self.guild_id}",
            )

    def _cancel_idle_timer_locked(self) -> None:
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    async def _idle_disconnect_after_delay(self) -> None:
        try:
            await asyncio.sleep(self._settings.idle_timeout_seconds)
            async with self._lock:
                if not self._should_idle_disconnect():
                    return
                channel_id = self._announce_channel_id
                self._ignore_current_end_locked()
                self._queue.reset()
                await self._backend.disconnect(self.guild_id)
                self._idle_task = None
                await self._controls.clear(self.guild_id)
                if channel_id is not None:
                    await self._presenter.notify(
                        channel_id,
                        "Disconnected",
                        "Left voice after the configured empty/idle timeout.",
                    )
        except asyncio.CancelledError:
            raise


class DefaultPlayerManager(BasePlayerManager):
    def __init__(
        self,
        backend: BaseAudioBackend,
        settings: BaseSettingsRepository,
        presenter: BasePresenter,
        controls: BasePlaybackControls,
        *,
        player_factory: GuildPlayerFactory,
        queue_factory: QueueFactory,
        queue_limit: int,
    ) -> None:
        self._backend = backend
        self._settings = settings
        self._presenter = presenter
        self._controls = controls
        self._player_factory = player_factory
        self._queue_factory = queue_factory
        self._queue_limit = queue_limit
        self._players: dict[int, BaseGuildPlayer] = {}
        self._lock = asyncio.Lock()
        backend.set_event_handler(self.handle_track_end)

    async def get_or_create(self, guild_id: int) -> BaseGuildPlayer:
        player = self._players.get(guild_id)
        if player is not None:
            return player
        async with self._lock:
            player = self._players.get(guild_id)
            if player is None:
                guild_settings = await self._settings.get(guild_id)
                player = self._player_factory(
                    guild_id,
                    self._backend,
                    self._queue_factory(),
                    self._presenter,
                    self._controls,
                    guild_settings,
                    queue_limit=self._queue_limit,
                )
                self._players[guild_id] = player
                self._controls.bind_player(player)
        return player

    def get(self, guild_id: int) -> BaseGuildPlayer | None:
        return self._players.get(guild_id)

    async def handle_track_end(
        self, guild_id: int, reason: PlaybackEndReason, backend_key: str | None
    ) -> None:
        player = self._players.get(guild_id)
        if player is not None:
            await player.handle_track_end(reason, backend_key)

    async def close(self) -> None:
        for player in tuple(self._players.values()):
            with contextlib.suppress(Exception):
                await player.leave()
        self._players.clear()
