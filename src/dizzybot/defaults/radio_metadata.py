from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit

import aiohttp

from dizzybot.contracts import BaseRadioMetadataProvider, BaseRadioResolver
from dizzybot.domain import RadioMetadata

LOGGER = logging.getLogger(__name__)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_STREAM_TITLE = re.compile(r"(?:^|;)StreamTitle='(.*?)';", re.DOTALL)
_EMPTY_TITLES = frozenset({"-", "--", "unknown", "unknown title"})
_AUDIO_EXTENSIONS = (".aac", ".flac", ".mp3", ".ogg", ".opus")


@dataclass(frozen=True, slots=True)
class _BauerStation:
    code: str
    name: str | None


class DefaultIcyMetadataProvider(BaseRadioMetadataProvider):
    """Read bounded ICY metadata blocks without opening a second long-lived stream."""

    MAX_REDIRECTS = 5
    MAX_METADATA_INTERVAL = 256 * 1024
    MAX_STATION_NAME_LENGTH = 256
    MAX_NOW_PLAYING_LENGTH = 1024

    def __init__(
        self,
        radio_resolver: BaseRadioResolver,
        *,
        timeout_seconds: float = 8.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._radio_resolver = radio_resolver
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _clean(value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        cleaned = "".join(
            character for character in value if character >= " " and character != "\x7f"
        )
        cleaned = " ".join(cleaned.split()).strip()
        if not cleaned:
            return None
        if len(cleaned) > limit:
            return f"{cleaned[: limit - 3]}..."
        return cleaned

    @classmethod
    def _decode_block(cls, block: bytes) -> str:
        unpadded = block.rstrip(b"\0")
        try:
            return unpadded.decode("utf-8")
        except UnicodeDecodeError:
            return unpadded.decode("cp1252", errors="replace")

    @classmethod
    def _metadata(cls, station_name: str | None, block: bytes) -> RadioMetadata:
        match = _STREAM_TITLE.search(cls._decode_block(block))
        now_playing = match.group(1) if match is not None else None
        now_playing = cls._clean(now_playing, cls.MAX_NOW_PLAYING_LENGTH)
        if now_playing is not None and now_playing.casefold() in _EMPTY_TITLES:
            now_playing = None
        return RadioMetadata(
            station_name=cls._clean(station_name, cls.MAX_STATION_NAME_LENGTH),
            now_playing=now_playing,
        )

    async def fetch(self, url: str) -> RadioMetadata | None:
        try:
            return await self._fetch(url)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Metadata is optional and must never interrupt otherwise healthy audio.
            LOGGER.debug("Could not read ICY metadata: %s", error)
            return None

    async def _fetch(self, url: str) -> RadioMetadata | None:
        current_url = await self._radio_resolver.validate_url(url)
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        headers = {
            "Accept": "audio/*,*/*;q=0.1",
            "Icy-MetaData": "1",
            "User-Agent": "DizzyBot/ICY metadata",
        }
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            for redirect_count in range(self.MAX_REDIRECTS + 1):
                async with session.get(
                    current_url,
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    if response.status in _REDIRECT_STATUSES:
                        location = response.headers.get("Location")
                        if location is None or redirect_count >= self.MAX_REDIRECTS:
                            return None
                        redirected_url = urljoin(str(response.url), location)
                        current_url = await self._radio_resolver.validate_url(redirected_url)
                        continue
                    if not 200 <= response.status < 300:
                        return None

                    station_name = response.headers.get("icy-name")
                    raw_interval = response.headers.get("icy-metaint")
                    if raw_interval is None:
                        return None
                    interval = int(raw_interval)
                    if not 1 <= interval <= self.MAX_METADATA_INTERVAL:
                        return None

                    await response.content.readexactly(interval)
                    block_size = (await response.content.readexactly(1))[0] * 16
                    block = await response.content.readexactly(block_size) if block_size else b""
                    return self._metadata(station_name, block)
        return None


class DefaultBauerMetadataProvider(BaseRadioMetadataProvider):
    """Read Bauer/Absolute now-playing data when personalised ICY streams omit it."""

    DEFAULT_API_BASE_URL = "https://listenapi.planetradio.co.uk/api9.2"
    MAX_RESPONSE_BYTES = 512 * 1024
    MAX_STATION_CODE_LENGTH = 64
    MAX_STATION_NAME_LENGTH = 256
    MAX_NOW_PLAYING_PART_LENGTH = 512

    def __init__(
        self,
        *,
        api_base_url: str = DEFAULT_API_BASE_URL,
        country_code: str = "GB",
        timeout_seconds: float = 8.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        parsed_base_url = urlsplit(api_base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("api_base_url must be an HTTP(S) URL")
        normalized_country_code = country_code.strip().upper()
        if len(normalized_country_code) != 2 or not normalized_country_code.isalpha():
            raise ValueError("country_code must be a two-letter code")

        self._api_base_url = api_base_url.rstrip("/")
        self._country_code = normalized_country_code
        self._timeout_seconds = timeout_seconds
        self._stations_by_mount: dict[str, _BauerStation] | None = None
        self._station_cache_lock = asyncio.Lock()

    @staticmethod
    def _clean(value: object, limit: int) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            return None
        if len(cleaned) > limit:
            return f"{cleaned[: limit - 3]}..."
        return cleaned

    @staticmethod
    def _mount_name(url: str) -> str | None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        for segment in reversed(parsed.path.split("/")):
            candidate = unquote(segment).strip().casefold()
            if candidate.endswith(_AUDIO_EXTENSIONS):
                return candidate
        return None

    async def fetch(self, url: str) -> RadioMetadata | None:
        try:
            mount_name = self._mount_name(url)
            if mount_name is None:
                return None

            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                stations = await self._station_map(session)
                station = stations.get(mount_name) if stations is not None else None
                if station is None:
                    return None

                payload = await self._request_json(
                    session,
                    f"nowplaying/{quote(station.code, safe='')}",
                )
                if not isinstance(payload, dict):
                    return None
                artist = self._clean(
                    payload.get("ArtistName"),
                    self.MAX_NOW_PLAYING_PART_LENGTH,
                )
                title = self._clean(
                    payload.get("TrackTitle"),
                    self.MAX_NOW_PLAYING_PART_LENGTH,
                )
                if artist is not None and title is not None:
                    now_playing = f"{artist} - {title}"
                else:
                    now_playing = title or artist
                return RadioMetadata(station_name=station.name, now_playing=now_playing)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # The upstream feed is optional; audio playback must remain independent.
            LOGGER.debug("Could not read Bauer radio metadata: %s", error)
            return None

    async def _station_map(
        self,
        session: aiohttp.ClientSession,
    ) -> dict[str, _BauerStation] | None:
        if self._stations_by_mount is not None:
            return self._stations_by_mount
        async with self._station_cache_lock:
            if self._stations_by_mount is not None:
                return self._stations_by_mount
            payload = await self._request_json(
                session,
                f"stations/{quote(self._country_code, safe='')}",
            )
            if not isinstance(payload, list):
                return None

            stations: dict[str, _BauerStation] = {}
            for raw_station in payload:
                if not isinstance(raw_station, dict):
                    continue
                code = self._clean(
                    raw_station.get("stationCode"),
                    self.MAX_STATION_CODE_LENGTH,
                )
                if code is None:
                    continue
                name = self._clean(
                    raw_station.get("stationName"),
                    self.MAX_STATION_NAME_LENGTH,
                )
                raw_streams = raw_station.get("stationStreams")
                if not isinstance(raw_streams, list):
                    continue
                station = _BauerStation(code=code, name=name)
                for raw_stream in raw_streams:
                    if not isinstance(raw_stream, dict):
                        continue
                    stream_url = raw_stream.get("streamUrl")
                    if not isinstance(stream_url, str):
                        continue
                    mount_name = self._mount_name(stream_url)
                    if mount_name is not None:
                        stations.setdefault(mount_name, station)

            self._stations_by_mount = stations
            return stations

    async def _request_json(
        self,
        session: aiohttp.ClientSession,
        path: str,
    ) -> Any | None:
        url = f"{self._api_base_url}/{path.lstrip('/')}"
        headers = {"Accept": "application/json", "User-Agent": "DizzyBot/radio metadata"}
        async with session.get(url, headers=headers) as response:
            if not 200 <= response.status < 300:
                return None
            raw_payload = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                raw_payload.extend(chunk)
                if len(raw_payload) > self.MAX_RESPONSE_BYTES:
                    return None
            return json.loads(raw_payload)


class DefaultRadioMetadataProvider(BaseRadioMetadataProvider):
    """Combine optional metadata providers, preferring the first useful track title."""

    def __init__(self, providers: Sequence[BaseRadioMetadataProvider]) -> None:
        self._providers = tuple(providers)
        if not self._providers:
            raise ValueError("at least one radio metadata provider is required")

    async def fetch(self, url: str) -> RadioMetadata | None:
        fallback: RadioMetadata | None = None
        for provider in self._providers:
            try:
                metadata = await provider.fetch(url)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("A radio metadata extension failed")
                continue
            if metadata is None:
                continue
            if metadata.now_playing is not None:
                return metadata
            if fallback is None:
                fallback = metadata
        return fallback
