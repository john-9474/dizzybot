from __future__ import annotations

from dataclasses import replace
from typing import Any

from dizzybot.contracts import (
    AudioEventHandler,
    BaseAudioBackend,
    BaseGuildPlayer,
    BasePlaybackControls,
    BasePresenter,
    BaseSettingsRepository,
)
from dizzybot.domain import (
    BackendLoadResult,
    GuildSettings,
    PlaybackEndReason,
    QueueSnapshot,
    Source,
    Track,
)


def make_track(
    identifier: str = "one",
    *,
    title: str | None = None,
    source: Source = Source.YOUTUBE,
    stream: bool = False,
    seekable: bool = True,
) -> Track:
    return Track(
        identifier=identifier,
        title=title or identifier.title(),
        author="Artist",
        uri=f"https://example.com/{identifier}",
        source=source,
        duration_ms=None if stream else 180_000,
        is_stream=stream,
        is_seekable=seekable,
        backend_key=f"encoded-{identifier}",
        backend_data=object(),
    )


class FakeAudioBackend(BaseAudioBackend):
    def __init__(self) -> None:
        self.handler: AudioEventHandler | None = None
        self.ready = True
        self.loaded = BackendLoadResult((make_track(),))
        self.connected: dict[int, int] = {}
        self.played: list[tuple[int, Track, int]] = []
        self.stopped: list[int] = []
        self.paused: dict[int, bool] = {}
        self.positions: dict[int, int] = {}
        self.volumes: dict[int, int] = {}
        self.fail_titles: set[str] = set()

    def set_event_handler(self, handler: AudioEventHandler) -> None:
        self.handler = handler

    async def start(self, client: Any) -> None:
        del client
        self.ready = True

    async def close(self) -> None:
        self.ready = False

    def is_ready(self) -> bool:
        return self.ready

    async def load_tracks(self, identifier: str) -> BackendLoadResult:
        del identifier
        return self.loaded

    async def connect(self, guild_id: int, channel: Any) -> None:
        self.connected[guild_id] = channel.id

    async def disconnect(self, guild_id: int) -> None:
        self.connected.pop(guild_id, None)

    async def play(self, guild_id: int, track: Track, volume: int) -> None:
        if track.title in self.fail_titles:
            raise RuntimeError("deliberate playback failure")
        self.paused[guild_id] = False
        self.played.append((guild_id, track, volume))

    async def stop(self, guild_id: int) -> None:
        self.stopped.append(guild_id)

    async def pause(self, guild_id: int, paused: bool) -> None:
        self.paused[guild_id] = paused

    async def seek(self, guild_id: int, position_ms: int) -> None:
        self.positions[guild_id] = position_ms

    async def set_volume(self, guild_id: int, volume: int) -> None:
        self.volumes[guild_id] = volume

    def is_connected(self, guild_id: int) -> bool:
        return guild_id in self.connected

    def channel_id(self, guild_id: int) -> int | None:
        return self.connected.get(guild_id)

    def position_ms(self, guild_id: int) -> int:
        return self.positions.get(guild_id, 0)

    def is_paused(self, guild_id: int) -> bool:
        return self.paused.get(guild_id, False)

    async def emit(
        self,
        guild_id: int,
        reason: PlaybackEndReason,
        backend_key: str | None,
    ) -> None:
        assert self.handler is not None
        await self.handler(guild_id, reason, backend_key)


class FakePresenter(BasePresenter):
    def __init__(self) -> None:
        self.client: Any | None = None
        self.responses: list[tuple[str, str, bool, bool]] = []
        self.notifications: list[tuple[int, str, str, bool]] = []

    def attach(self, client: Any) -> None:
        self.client = client

    async def respond(
        self,
        interaction: Any,
        title: str,
        description: str,
        *,
        error: bool = False,
        ephemeral: bool = False,
    ) -> None:
        del interaction
        self.responses.append((title, description, error, ephemeral))

    async def notify(
        self,
        channel_id: int,
        title: str,
        description: str,
        *,
        error: bool = False,
    ) -> None:
        self.notifications.append((channel_id, title, description, error))

    def now_playing_embed(self, snapshot: QueueSnapshot) -> Any:
        return {"current": snapshot.current, "paused": snapshot.paused}

    async def respond_now_playing(self, interaction: Any, snapshot: QueueSnapshot) -> None:
        del interaction
        title = "Paused" if snapshot.paused else "Now playing"
        current = snapshot.current.title if snapshot.current else "Nothing"
        self.responses.append((title, current, False, False))

    def track_description(self, track: Track) -> str:
        return track.title

    def queue_page(self, snapshot: QueueSnapshot, page: int) -> tuple[str, str]:
        return f"Page {page}", f"{len(snapshot.upcoming)} tracks"


class FakePlaybackControls(BasePlaybackControls):
    def __init__(self) -> None:
        self.players: dict[int, BaseGuildPlayer] = {}
        self.updates: list[tuple[int, int, QueueSnapshot]] = []
        self.cleared: list[int] = []

    def bind_player(self, player: BaseGuildPlayer) -> None:
        self.players[player.guild_id] = player

    async def update(self, guild_id: int, channel_id: int, snapshot: QueueSnapshot) -> None:
        self.updates.append((guild_id, channel_id, snapshot))

    async def clear(self, guild_id: int) -> None:
        self.cleared.append(guild_id)


class FakeSettingsRepository(BaseSettingsRepository):
    def __init__(self, default: GuildSettings | None = None) -> None:
        self.default = default or GuildSettings(guild_id=0)
        self.rows: dict[int, GuildSettings] = {}
        self.ready = False

    async def start(self) -> None:
        self.ready = True

    async def close(self) -> None:
        self.ready = False

    def is_ready(self) -> bool:
        return self.ready

    async def get(self, guild_id: int) -> GuildSettings:
        return self.rows.get(guild_id, replace(self.default, guild_id=guild_id))

    async def save(self, settings: GuildSettings) -> GuildSettings:
        self.rows[settings.guild_id] = settings
        return settings

    async def reset(self, guild_id: int) -> GuildSettings:
        self.rows.pop(guild_id, None)
        return replace(self.default, guild_id=guild_id)
