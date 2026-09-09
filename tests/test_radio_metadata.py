from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from dizzybot.contracts import BaseRadioMetadataProvider, BaseRadioResolver
from dizzybot.defaults.radio_metadata import (
    DefaultBauerMetadataProvider,
    DefaultIcyMetadataProvider,
    DefaultRadioMetadataProvider,
)
from dizzybot.domain import RadioMetadata, RadioStation, ResolveResult


class PassthroughRadioResolver(BaseRadioResolver):
    def __init__(self) -> None:
        self.validated: list[str] = []

    async def validate_url(self, url: str) -> str:
        self.validated.append(url)
        return url

    async def resolve(self, station: RadioStation, requester_id: int) -> ResolveResult:
        del station, requester_id
        raise AssertionError("Playback resolution is not used for metadata")


def icy_response(station_name: str, stream_title: str) -> bytes:
    metadata = f"StreamTitle='{stream_title}';StreamUrl='';".encode()
    padded_size = ((len(metadata) + 15) // 16) * 16
    block = metadata.ljust(padded_size, b"\0")
    body = b"A" * 16 + bytes((padded_size // 16,)) + block
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: audio/mpeg\r\n"
        + f"icy-name: {station_name}\r\n".encode()
        + b"icy-metaint: 16\r\n"
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
        + body
    )


async def test_icy_metadata_provider_validates_redirect_and_reads_first_metadata_block() -> None:
    response = icy_response("Test FM", "Artist - Track")

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        if request.startswith(b"GET /redirect "):
            writer.write(
                b"HTTP/1.1 302 Found\r\n"
                b"Location: /stream\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
        else:
            writer.write(response)
        await writer.drain()
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    assert server.sockets
    port = server.sockets[0].getsockname()[1]
    resolver = PassthroughRadioResolver()
    provider = DefaultIcyMetadataProvider(resolver)
    url = f"http://127.0.0.1:{port}/redirect"
    try:
        metadata = await provider.fetch(url)
    finally:
        server.close()
        await server.wait_closed()

    assert metadata == RadioMetadata(station_name="Test FM", now_playing="Artist - Track")
    assert resolver.validated == [url, f"http://127.0.0.1:{port}/stream"]


async def test_icy_metadata_provider_treats_failures_as_optional() -> None:
    class RejectingResolver(PassthroughRadioResolver):
        async def validate_url(self, url: str) -> str:
            raise ValueError(url)

    provider = DefaultIcyMetadataProvider(RejectingResolver())
    assert await provider.fetch("https://radio.invalid/stream") is None


def test_icy_metadata_provider_validates_timeout_and_cleans_metadata() -> None:
    resolver = PassthroughRadioResolver()
    with pytest.raises(ValueError, match="positive"):
        DefaultIcyMetadataProvider(resolver, timeout_seconds=0)

    metadata = DefaultIcyMetadataProvider._metadata(
        "  Test\x7f   FM  ",
        b"StreamTitle='  Guns N' Roses  -  Track  ';\0\0",
    )
    assert metadata == RadioMetadata(
        station_name="Test FM",
        now_playing="Guns N' Roses - Track",
    )
    assert DefaultIcyMetadataProvider._metadata("Test FM", b"StreamTitle='-';").now_playing is None


async def test_bauer_metadata_provider_matches_absolute_stream_and_caches_stations() -> None:
    request_counts = {"stations": 0, "nowplaying": 0}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        path = request.split(b" ", 2)[1]
        if path == b"/stations/GB":
            request_counts["stations"] += 1
            payload: object = [
                {
                    "stationCode": "ab0",
                    "stationName": "Absolute Radio 00s",
                    "stationStreams": [
                        {
                            "streamUrl": (
                                "https://stream-ar.hellorayo.co.uk/absolute00shigh.aac?direct=true"
                            )
                        },
                        {
                            "streamUrl": (
                                "https://hls-ar.hellorayo.co.uk/absolute00shigh.aac/playlist.m3u8"
                            )
                        },
                    ],
                }
            ]
        elif path == b"/nowplaying/ab0":
            request_counts["nowplaying"] += 1
            payload = {
                "ArtistName": "The White Stripes",
                "TrackTitle": "The Hardest Button To Button",
            }
        else:
            payload = None

        body = json.dumps(payload).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    assert server.sockets
    port = server.sockets[0].getsockname()[1]
    provider = DefaultBauerMetadataProvider(api_base_url=f"http://127.0.0.1:{port}")
    stream_url = "https://live-absolute.sharp-stream.com/absolute00shigh.aac"
    try:
        first = await provider.fetch(stream_url)
        second = await provider.fetch(stream_url)
    finally:
        server.close()
        await server.wait_closed()

    expected = RadioMetadata(
        station_name="Absolute Radio 00s",
        now_playing="The White Stripes - The Hardest Button To Button",
    )
    assert first == expected
    assert second == expected
    assert request_counts == {"stations": 1, "nowplaying": 2}


async def test_bauer_metadata_provider_ignores_urls_without_audio_mounts() -> None:
    provider = DefaultBauerMetadataProvider(api_base_url="http://127.0.0.1:1")
    assert await provider.fetch("https://streaming.radio.co/listen") is None


async def test_combined_metadata_provider_uses_next_provider_for_blank_metadata() -> None:
    class StaticProvider(BaseRadioMetadataProvider):
        def __init__(self, metadata: RadioMetadata | None) -> None:
            self.metadata = metadata
            self.urls: list[str] = []

        async def fetch(self, url: str) -> RadioMetadata | None:
            self.urls.append(url)
            return self.metadata

    blank = StaticProvider(RadioMetadata(station_name="Station", now_playing=None))
    titled = StaticProvider(RadioMetadata(station_name=None, now_playing="Artist - Track"))
    provider = DefaultRadioMetadataProvider((blank, titled))

    url = "https://radio.example/stream.aac"
    assert await provider.fetch(url) == RadioMetadata(
        station_name=None,
        now_playing="Artist - Track",
    )
    assert blank.urls == [url]
    assert titled.urls == [url]


def test_bauer_and_combined_metadata_provider_validate_configuration() -> None:
    with pytest.raises(ValueError, match="positive"):
        DefaultBauerMetadataProvider(timeout_seconds=0)
    with pytest.raises(ValueError, match="HTTP"):
        DefaultBauerMetadataProvider(api_base_url="not-a-url")
    with pytest.raises(ValueError, match="two-letter"):
        DefaultBauerMetadataProvider(country_code="Britain")
    with pytest.raises(ValueError, match="at least one"):
        DefaultRadioMetadataProvider(())
