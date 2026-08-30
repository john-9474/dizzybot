from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import wavelink

from dizzybot.config import LavalinkConfig
from dizzybot.defaults.audio import DefaultAudioBackend
from dizzybot.domain import PlaybackEndReason, Source
from dizzybot.errors import AudioBackendError, MediaUnavailableError, PlayerStateError


def playable(
    identifier: str = "id", *, source: str = "youtube", stream: bool = False
) -> wavelink.Playable:
    return wavelink.Playable(
        {
            "encoded": f"encoded-{identifier}",
            "info": {
                "identifier": identifier,
                "isSeekable": not stream,
                "author": "Artist",
                "length": 1000,
                "isStream": stream,
                "position": 0,
                "title": "Song",
                "uri": "https://example.com/song",
                "artworkUrl": None,
                "isrc": None,
                "sourceName": source,
            },
            "pluginInfo": {},
            "userData": {},
        }
    )


class FakeWavelinkPlayer:
    def __init__(self, channel_id: int) -> None:
        self.connected = True
        self.channel = SimpleNamespace(id=channel_id)
        self.current: Any | None = object()
        self.position = 12
        self.paused = False
        self.volume = 100
        self.played: Any | None = None

    async def disconnect(self) -> None:
        self.connected = False

    async def play(self, track: Any, **kwargs: Any) -> None:
        self.played = track
        self.volume = kwargs["volume"]

    async def skip(self, **kwargs: Any) -> None:
        self.current = None

    async def pause(self, value: bool) -> None:
        self.paused = value

    async def seek(self, value: int) -> None:
        self.position = value

    async def set_volume(self, value: int) -> None:
        self.volume = value


def backend() -> DefaultAudioBackend:
    return DefaultAudioBackend(LavalinkConfig(password="password"))


async def test_audio_start_close_and_listeners(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = backend()
    listeners: list[str] = []
    client = SimpleNamespace(add_listener=lambda callback, name: listeners.append(name))

    async def connect(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {}

    async def close() -> None:
        return None

    monkeypatch.setattr(wavelink.Pool, "connect", connect)
    monkeypatch.setattr(wavelink.Pool, "close", close)
    await audio.start(client)
    assert audio.is_ready() is True
    assert "on_wavelink_track_end" in listeners
    await audio.close()
    assert audio.is_ready() is False


async def test_audio_loads_lists_playlists_and_maps_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = backend()
    audio._ready = True

    async def fetch_list(query: str) -> list[wavelink.Playable]:
        del query
        return [playable(source="soundcloud")]

    monkeypatch.setattr(wavelink.Pool, "fetch_tracks", fetch_list)
    result = await audio.load_tracks("scsearch:test")
    assert result.tracks[0].source is Source.SOUNDCLOUD

    async def fetch_http(query: str) -> list[wavelink.Playable]:
        del query
        return [playable(source="http", stream=True)]

    monkeypatch.setattr(wavelink.Pool, "fetch_tracks", fetch_http)
    result = await audio.load_tracks("https://radio.example/stream")
    assert result.tracks[0].source is Source.RADIO

    playlist = wavelink.Playlist(
        {
            "info": {"name": "List", "selectedTrack": -1},
            "pluginInfo": {},
            "tracks": [playable("spotify", source="spotify").raw_data],
        }
    )

    async def fetch_playlist(query: str) -> wavelink.Playlist:
        del query
        return playlist

    monkeypatch.setattr(wavelink.Pool, "fetch_tracks", fetch_playlist)
    result = await audio.load_tracks("spotify-url")
    assert result.playlist_name == "List"
    assert result.tracks[0].source is Source.SPOTIFY


async def test_audio_load_failure_and_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = backend()
    with pytest.raises(AudioBackendError):
        await audio.load_tracks("test")
    audio._ready = True

    async def fail(query: str) -> list[wavelink.Playable]:
        del query
        raise RuntimeError("failure")

    monkeypatch.setattr(wavelink.Pool, "fetch_tracks", fail)
    with pytest.raises(MediaUnavailableError):
        await audio.load_tracks("test")


async def test_audio_player_controls_and_events(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    audio = backend()
    player = FakeWavelinkPlayer(5)

    async def channel_connect(**kwargs: Any) -> FakeWavelinkPlayer:
        del kwargs
        return player

    channel = SimpleNamespace(id=5, connect=channel_connect)
    await audio.connect(1, channel)
    track = audio._track(playable())
    await audio.play(1, track, 70)
    await audio.pause(1, True)
    await audio.seek(1, 500)
    await audio.set_volume(1, 50)
    assert audio.is_connected(1) is True
    assert audio.channel_id(1) == 5
    assert audio.position_ms(1) == 500
    assert audio.is_paused(1) is True
    await audio.stop(1)

    events: list[tuple[int, PlaybackEndReason, str | None]] = []

    async def handler(guild_id: int, reason: PlaybackEndReason, key: str | None) -> None:
        events.append((guild_id, reason, key))

    audio.set_event_handler(handler)
    event_player = SimpleNamespace(guild=SimpleNamespace(id=1))
    event_track = playable()
    await audio._on_track_end(
        SimpleNamespace(
            player=event_player, reason="finished", original=event_track, track=event_track
        )
    )
    await audio._on_track_exception(SimpleNamespace(player=event_player, track=event_track))
    await audio._on_track_stuck(SimpleNamespace(player=event_player, track=event_track))
    assert [event[1] for event in events] == [
        PlaybackEndReason.FINISHED,
        PlaybackEndReason.LOAD_FAILED,
        PlaybackEndReason.STUCK,
    ]
    await audio.disconnect(1)
    assert audio.is_connected(1) is False
    with pytest.raises(PlayerStateError):
        await audio.pause(1, True)


async def test_audio_refreshes_soundcloud_track_before_playback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = backend()
    player = FakeWavelinkPlayer(5)

    async def channel_connect(**kwargs: Any) -> FakeWavelinkPlayer:
        del kwargs
        return player

    await audio.connect(1, SimpleNamespace(id=5, connect=channel_connect))
    original = playable("soundcloud-id", source="soundcloud")
    fresh_data = dict(original.raw_data)
    fresh_data["encoded"] = "fresh-encoded"
    fresh = wavelink.Playable(fresh_data)

    async def fetch_tracks(query: str) -> list[wavelink.Playable]:
        assert query == original.uri
        return [fresh]

    monkeypatch.setattr(wavelink.Pool, "fetch_tracks", fetch_tracks)
    track = audio._track(original)
    await audio.play(1, track, 70)
    assert player.played is fresh

    events: list[tuple[int, PlaybackEndReason, str | None]] = []

    async def handler(guild_id: int, reason: PlaybackEndReason, key: str | None) -> None:
        events.append((guild_id, reason, key))

    audio.set_event_handler(handler)
    event_player = SimpleNamespace(guild=SimpleNamespace(id=1))
    await audio._on_track_end(
        SimpleNamespace(player=event_player, reason="finished", original=fresh, track=fresh)
    )
    assert events[-1][2] == original.encoded
