from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin

import aiohttp

from dizzybot.contracts import BaseRadioMetadataProvider, BaseRadioResolver
from dizzybot.domain import RadioMetadata

LOGGER = logging.getLogger(__name__)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_STREAM_TITLE = re.compile(r"(?:^|;)StreamTitle='(.*?)';", re.DOTALL)
_EMPTY_TITLES = frozenset({"-", "--", "unknown", "unknown title"})


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
