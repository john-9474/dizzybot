from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from typing import ClassVar
from urllib.parse import urlparse

from dizzybot.contracts import BaseAudioBackend, BaseTrackResolver
from dizzybot.domain import Playlist, ResolveRequest, ResolveResult, Source
from dizzybot.errors import InvalidRequestError, MediaUnavailableError, SourceUnavailableError


class DefaultTrackResolver(BaseTrackResolver):
    _SOURCE_HOSTS: tuple[tuple[Source, tuple[str, ...]], ...] = (
        (Source.YOUTUBE, ("youtube.com", "youtu.be")),
        (Source.SOUNDCLOUD, ("soundcloud.com",)),
        (Source.SPOTIFY, ("spotify.com", "spotify.link")),
        (Source.APPLE_MUSIC, ("music.apple.com",)),
        (Source.TIDAL, ("tidal.com",)),
        (Source.BANDCAMP, ("bandcamp.com",)),
    )
    _SEARCH_PREFIXES: ClassVar[dict[Source, str]] = {
        Source.YOUTUBE: "ytsearch:",
        Source.SOUNDCLOUD: "scsearch:",
        Source.SPOTIFY: "spsearch:",
        Source.APPLE_MUSIC: "amsearch:",
        Source.TIDAL: "tdsearch:",
        Source.BANDCAMP: "bcsearch:",
    }
    _UNAVAILABLE_MESSAGES: ClassVar[dict[Source, str]] = {
        Source.SPOTIFY: (
            "Spotify is unavailable. Provide both SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET."
        ),
        Source.TIDAL: "TIDAL is unavailable. Provide TIDAL_TOKEN.",
    }

    def __init__(self, backend: BaseAudioBackend, *, available_sources: Collection[Source]) -> None:
        self._backend = backend
        self._available_sources = frozenset(available_sources)

    def detect_source(self, query: str) -> Source | None:
        parsed = urlparse(query.strip())
        if parsed.scheme not in {"http", "https"}:
            return None
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        for source, domains in self._SOURCE_HOSTS:
            if any(host == domain or host.endswith(f".{domain}") for domain in domains):
                return source
        return None

    async def resolve(self, request: ResolveRequest) -> ResolveResult:
        query = request.query.strip()
        if not query:
            raise InvalidRequestError("Search text or a supported URL is required.")

        detected = self.detect_source(query)
        is_url = urlparse(query).scheme in {"http", "https"}
        if is_url and detected is None:
            raise InvalidRequestError(
                "Only YouTube, SoundCloud, Spotify, Apple Music, TIDAL, and Bandcamp "
                "URLs are supported."
            )

        requested_source = (
            request.default_source if request.source is Source.AUTO else request.source
        )
        source = detected or requested_source
        if detected is not None and request.source not in {Source.AUTO, detected}:
            raise InvalidRequestError(
                f"That URL is from {detected.value}, not {request.source.value}."
            )
        if source is Source.AUTO:
            source = Source.YOUTUBE
        if source is Source.RADIO:
            raise InvalidRequestError("Use `/radio play` to play a saved radio station.")
        if source not in self._available_sources:
            raise SourceUnavailableError(
                self._UNAVAILABLE_MESSAGES.get(
                    source, f"{source.value.replace('_', ' ').title()} is unavailable."
                )
            )

        identifier = query if detected is not None else f"{self._SEARCH_PREFIXES[source]}{query}"
        loaded = await self._backend.load_tracks(identifier)
        candidates = loaded.tracks if loaded.playlist_name else loaded.tracks[:1]
        playable = [
            track.requested(request.requester_id) for track in candidates if not track.is_stream
        ]
        skipped = len(candidates) - len(playable)
        truncated = len(playable) > request.max_items
        if truncated:
            skipped += len(playable) - request.max_items
            playable = playable[: request.max_items]
        if not playable:
            raise MediaUnavailableError("No non-live, playable tracks were found.")

        tracks = tuple(playable)
        playlist = None
        if loaded.playlist_name is not None:
            tracks = tuple(
                replace(
                    track,
                    playlist_name=loaded.playlist_name,
                    playlist_position=index,
                    playlist_size=len(tracks),
                )
                for index, track in enumerate(tracks, start=1)
            )
            playlist = Playlist(name=loaded.playlist_name, source=source, tracks=tracks)
        return ResolveResult(
            tracks=tracks,
            playlist=playlist,
            skipped_count=skipped,
            truncated=truncated,
        )
