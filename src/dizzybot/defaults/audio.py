from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from typing import Any, ClassVar

import wavelink

from dizzybot.config import LavalinkConfig
from dizzybot.contracts import AudioEventHandler, BaseAudioBackend
from dizzybot.domain import BackendLoadResult, PlaybackEndReason, Source, Track
from dizzybot.errors import AudioBackendError, MediaUnavailableError, PlayerStateError

LOGGER = logging.getLogger(__name__)


class DefaultAudioBackend(BaseAudioBackend):
    _END_REASONS: ClassVar[dict[str, PlaybackEndReason]] = {
        "finished": PlaybackEndReason.FINISHED,
        "loadfailed": PlaybackEndReason.LOAD_FAILED,
        "stopped": PlaybackEndReason.STOPPED,
        "replaced": PlaybackEndReason.REPLACED,
        "cleanup": PlaybackEndReason.DISCONNECTED,
    }

    def __init__(self, config: LavalinkConfig) -> None:
        self._config = config
        self._handler: AudioEventHandler | None = None
        self._players: dict[int, wavelink.Player] = {}
        self._backend_key_aliases: dict[int, dict[str, str]] = {}
        self._track_exceptions: dict[int, Counter[str]] = {}
        self._ready = False
        self._client: Any | None = None

    def set_event_handler(self, handler: AudioEventHandler) -> None:
        self._handler = handler

    async def start(self, client: Any) -> None:
        self._client = client
        node = wavelink.Node(
            identifier=self._config.identifier,
            uri=self._config.uri,
            password=self._config.password.get_secret_value(),
            retries=self._config.connect_retries,
            inactive_player_timeout=None,
            inactive_channel_tokens=None,
        )
        try:
            await wavelink.Pool.connect(nodes=[node], client=client, cache_capacity=100)
        except Exception as error:
            raise AudioBackendError("Could not connect to Lavalink.") from error
        client.add_listener(self._on_track_end, "on_wavelink_track_end")
        client.add_listener(self._on_track_exception, "on_wavelink_track_exception")
        client.add_listener(self._on_track_stuck, "on_wavelink_track_stuck")
        client.add_listener(self._on_node_ready, "on_wavelink_node_ready")
        client.add_listener(self._on_node_closed, "on_wavelink_node_closed")
        self._ready = True

    async def close(self) -> None:
        self._ready = False
        for guild_id in tuple(self._players):
            await self.disconnect(guild_id)
        await wavelink.Pool.close()
        self._players.clear()

    def is_ready(self) -> bool:
        return self._ready

    @staticmethod
    def _source(value: str) -> Source:
        normalized = value.lower()
        if "soundcloud" in normalized:
            return Source.SOUNDCLOUD
        if "spotify" in normalized:
            return Source.SPOTIFY
        if "apple" in normalized:
            return Source.APPLE_MUSIC
        if "tidal" in normalized:
            return Source.TIDAL
        if "bandcamp" in normalized:
            return Source.BANDCAMP
        if "http" in normalized:
            return Source.RADIO
        return Source.YOUTUBE

    @classmethod
    def _track(cls, playable: wavelink.Playable) -> Track:
        return Track(
            identifier=playable.identifier,
            title=playable.title,
            author=playable.author,
            uri=playable.uri or "https://discord.com",
            source=cls._source(playable.source),
            duration_ms=None if playable.is_stream else playable.length,
            artwork_url=playable.artwork,
            is_stream=playable.is_stream,
            is_seekable=playable.is_seekable,
            backend_key=playable.encoded,
            backend_data=playable,
        )

    async def load_tracks(self, identifier: str) -> BackendLoadResult:
        if not self._ready:
            raise AudioBackendError()
        try:
            loaded = await wavelink.Pool.fetch_tracks(identifier)
        except Exception as error:
            LOGGER.warning("Lavalink failed to load %r: %s", identifier, error)
            raise MediaUnavailableError("The audio service could not load that media.") from error
        if isinstance(loaded, wavelink.Playlist):
            playables: Iterable[wavelink.Playable] = loaded.tracks
            playlist_name: str | None = loaded.name
        else:
            playables = loaded
            playlist_name = None
        return BackendLoadResult(
            tracks=tuple(self._track(track) for track in playables),
            playlist_name=playlist_name,
        )

    async def connect(self, guild_id: int, channel: Any) -> None:
        current = self._players.get(guild_id)
        if current is not None and current.connected:
            if current.channel.id != channel.id:
                raise PlayerStateError(
                    "The bot is already active in another channel; disconnect it first."
                )
            return
        try:
            player = await channel.connect(cls=wavelink.Player, self_deaf=True)
        except Exception as error:
            raise AudioBackendError("Could not join that voice channel.") from error
        self._players[guild_id] = player

    async def disconnect(self, guild_id: int) -> None:
        player = self._players.pop(guild_id, None)
        self._backend_key_aliases.pop(guild_id, None)
        self._track_exceptions.pop(guild_id, None)
        if player is not None and player.connected:
            await player.disconnect()

    def _player(self, guild_id: int) -> wavelink.Player:
        player = self._players.get(guild_id)
        if player is None or not player.connected:
            raise PlayerStateError()
        return player

    async def play(self, guild_id: int, track: Track, volume: int) -> None:
        if not isinstance(track.backend_data, wavelink.Playable):
            raise AudioBackendError("The selected audio backend cannot play that track.")
        playable = track.backend_data
        if track.source is Source.SOUNDCLOUD:
            playable = await self._refresh_soundcloud_track(track, playable)
        elif track.source is Source.RADIO:
            playable = await self._refresh_radio_track(track, playable)
        if playable.encoded and track.backend_key:
            aliases = self._backend_key_aliases.setdefault(guild_id, {})
            aliases[playable.encoded] = track.backend_key
        await self._player(guild_id).play(playable, volume=volume, replace=True)

    async def _refresh_soundcloud_track(
        self, track: Track, original: wavelink.Playable
    ) -> wavelink.Playable:
        """Refresh SoundCloud's expiring media URL immediately before playback."""
        try:
            loaded = await wavelink.Pool.fetch_tracks(track.uri)
        except Exception as error:
            LOGGER.warning("Could not refresh SoundCloud track %r: %s", track.uri, error)
            return original
        candidates = loaded.tracks if isinstance(loaded, wavelink.Playlist) else loaded
        return next(
            (candidate for candidate in candidates if candidate.identifier == track.identifier),
            candidates[0] if candidates else original,
        )

    async def _refresh_radio_track(
        self, track: Track, original: wavelink.Playable
    ) -> wavelink.Playable:
        """Reload a live stream so a reconnect uses a fresh manifest or media URL."""
        try:
            loaded = await wavelink.Pool.fetch_tracks(track.uri)
        except Exception as error:
            LOGGER.warning("Could not refresh radio stream %r: %s", track.uri, error)
            return original
        candidates = loaded.tracks if isinstance(loaded, wavelink.Playlist) else loaded
        return candidates[0] if candidates else original

    async def stop(self, guild_id: int) -> None:
        player = self._player(guild_id)
        if player.current is not None:
            await player.skip(force=True)

    async def pause(self, guild_id: int, paused: bool) -> None:
        await self._player(guild_id).pause(paused)

    async def seek(self, guild_id: int, position_ms: int) -> None:
        await self._player(guild_id).seek(position_ms)

    async def set_volume(self, guild_id: int, volume: int) -> None:
        await self._player(guild_id).set_volume(volume)

    def is_connected(self, guild_id: int) -> bool:
        player = self._players.get(guild_id)
        return bool(player and player.connected)

    def channel_id(self, guild_id: int) -> int | None:
        player = self._players.get(guild_id)
        return player.channel.id if player and player.connected else None

    def position_ms(self, guild_id: int) -> int:
        player = self._players.get(guild_id)
        return player.position if player and player.connected else 0

    def is_paused(self, guild_id: int) -> bool:
        player = self._players.get(guild_id)
        return bool(player and player.paused)

    @staticmethod
    def _guild_id(payload: Any) -> int | None:
        player = getattr(payload, "player", None)
        guild = getattr(player, "guild", None)
        return getattr(guild, "id", None)

    @staticmethod
    def _backend_key(payload: Any) -> str | None:
        original = getattr(payload, "original", None)
        track = original or getattr(payload, "track", None)
        return getattr(track, "encoded", None)

    async def _dispatch(self, payload: Any, reason: PlaybackEndReason) -> None:
        guild_id = self._guild_id(payload)
        if guild_id is not None and self._handler is not None:
            backend_key = self._backend_key(payload)
            if backend_key is not None:
                aliases = self._backend_key_aliases.get(guild_id, {})
                backend_key = aliases.pop(backend_key, backend_key)
            await self._handler(guild_id, reason, backend_key)

    async def _on_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        reason = self._END_REASONS.get(payload.reason.lower(), PlaybackEndReason.STOPPED)
        guild_id = self._guild_id(payload)
        backend_key = self._backend_key(payload)
        if guild_id is not None and backend_key is not None:
            exceptions = self._track_exceptions.get(guild_id)
            if exceptions and exceptions[backend_key]:
                exceptions[backend_key] -= 1
                if not exceptions[backend_key]:
                    del exceptions[backend_key]
                if not exceptions:
                    self._track_exceptions.pop(guild_id, None)
                reason = PlaybackEndReason.LOAD_FAILED
        await self._dispatch(payload, reason)

    async def _on_track_exception(self, payload: wavelink.TrackExceptionEventPayload) -> None:
        # Lavalink follows a TrackExceptionEvent with a TrackEndEvent. Remember
        # the exception and normalize that single end event as a load failure,
        # avoiding two independent queue advances for the same track.
        guild_id = self._guild_id(payload)
        backend_key = self._backend_key(payload)
        if guild_id is None or backend_key is None:
            await self._dispatch(payload, PlaybackEndReason.LOAD_FAILED)
            return
        self._track_exceptions.setdefault(guild_id, Counter())[backend_key] += 1

    async def _on_track_stuck(self, payload: wavelink.TrackStuckEventPayload) -> None:
        await self._dispatch(payload, PlaybackEndReason.STUCK)

    async def _on_node_ready(self, payload: Any) -> None:
        self._ready = True

    async def _on_node_closed(self, node: Any, disconnected: Any) -> None:
        del node, disconnected
        self._ready = False
