"""Stable application types which do not depend on Discord or Wavelink."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class Source(StrEnum):
    AUTO = "auto"
    YOUTUBE = "youtube"
    SOUNDCLOUD = "soundcloud"
    SPOTIFY = "spotify"
    APPLE_MUSIC = "apple_music"
    TIDAL = "tidal"
    BANDCAMP = "bandcamp"
    RADIO = "radio"


class RepeatMode(StrEnum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class PlaybackEndReason(StrEnum):
    FINISHED = "finished"
    SKIPPED = "skipped"
    STOPPED = "stopped"
    REPLACED = "replaced"
    LOAD_FAILED = "load_failed"
    STUCK = "stuck"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True, slots=True)
class Track:
    identifier: str
    title: str
    author: str
    uri: str
    source: Source
    duration_ms: int | None
    artwork_url: str | None = None
    is_stream: bool = False
    is_seekable: bool = True
    requested_by: int | None = None
    backend_key: str = ""
    backend_data: Any = field(default=None, repr=False, compare=False)
    playlist_name: str | None = None
    playlist_position: int | None = None
    playlist_size: int | None = None

    @property
    def duration_seconds(self) -> int | None:
        return None if self.duration_ms is None else self.duration_ms // 1000

    def requested(self, user_id: int) -> Track:
        return replace(self, requested_by=user_id)


@dataclass(frozen=True, slots=True)
class Playlist:
    name: str
    source: Source
    tracks: tuple[Track, ...]


@dataclass(frozen=True, slots=True)
class ResolveRequest:
    query: str
    source: Source
    requester_id: int
    max_items: int
    default_source: Source = Source.YOUTUBE


@dataclass(frozen=True, slots=True)
class ResolveResult:
    tracks: tuple[Track, ...]
    playlist: Playlist | None = None
    skipped_count: int = 0
    truncated: bool = False

    @property
    def is_playlist(self) -> bool:
        return self.playlist is not None


@dataclass(frozen=True, slots=True)
class BackendLoadResult:
    tracks: tuple[Track, ...]
    playlist_name: str | None = None


@dataclass(frozen=True, slots=True)
class GuildSettings:
    guild_id: int
    default_volume: int = 75
    idle_timeout_seconds: int = 300
    stay_connected: bool = False
    dj_role_id: int | None = None
    default_search_source: Source = Source.YOUTUBE


@dataclass(frozen=True, slots=True)
class RadioStation:
    guild_id: int
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    current: Track | None
    upcoming: tuple[Track, ...]
    repeat_mode: RepeatMode
    volume: int
    paused: bool
    position_ms: int = 0
    queue_position: int | None = None
    queue_total: int = 0
    can_go_previous: bool = False


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    live: bool
    ready: bool
    discord_ready: bool
    audio_ready: bool
    storage_ready: bool
