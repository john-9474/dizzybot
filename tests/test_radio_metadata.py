from __future__ import annotations

import asyncio
import contextlib

import pytest

from dizzybot.contracts import BaseRadioResolver
from dizzybot.defaults.radio_metadata import DefaultIcyMetadataProvider
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
