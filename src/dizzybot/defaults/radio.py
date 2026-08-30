from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Collection
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit

from dizzybot.contracts import BaseAudioBackend, BaseRadioResolver
from dizzybot.domain import RadioStation, ResolveResult, Source
from dizzybot.errors import InvalidRequestError, MediaUnavailableError

AddressResolver = Callable[[str, int], Awaitable[Collection[str]]]


class DefaultRadioResolver(BaseRadioResolver):
    """Validate public stream URLs and turn Lavalink HTTP tracks into radio tracks."""

    def __init__(
        self,
        backend: BaseAudioBackend,
        *,
        allow_private_networks: bool = False,
        address_resolver: AddressResolver | None = None,
    ) -> None:
        self._backend = backend
        self._allow_private_networks = allow_private_networks
        self._address_resolver = address_resolver or self._resolve_addresses

    @staticmethod
    async def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()
        addresses = await loop.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
        return tuple({str(address[4][0]) for address in addresses})

    async def validate_url(self, url: str) -> str:
        value = url.strip()
        if not value or len(value) > 2048:
            raise InvalidRequestError("The radio stream URL must be between 1 and 2048 characters.")
        if any(character.isspace() or character in "<>" for character in value):
            raise InvalidRequestError("The radio stream URL contains invalid characters.")

        try:
            parsed = urlsplit(value)
            explicit_port = parsed.port
        except ValueError as error:
            raise InvalidRequestError("That is not a valid radio stream URL.") from error
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise InvalidRequestError("Radio streams must use an http:// or https:// URL.")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidRequestError("Radio stream URLs cannot contain credentials.")
        if parsed.hostname is None:
            raise InvalidRequestError("The radio stream URL must include a host.")

        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise InvalidRequestError("The radio stream host is not valid.") from error
        port = explicit_port or (443 if scheme == "https" else 80)

        try:
            literal_address = ipaddress.ip_address(host)
        except ValueError:
            try:
                addresses = await asyncio.wait_for(self._address_resolver(host, port), timeout=5.0)
                resolved = tuple(ipaddress.ip_address(address) for address in addresses)
            except (OSError, TimeoutError, ValueError) as error:
                raise InvalidRequestError("The radio stream host could not be resolved.") from error
        else:
            resolved = (literal_address,)

        if not resolved:
            raise InvalidRequestError("The radio stream host could not be resolved.")
        if not self._allow_private_networks and any(not address.is_global for address in resolved):
            raise InvalidRequestError(
                "Radio streams must use a public internet address; private and local hosts "
                "are blocked."
            )

        display_host = f"[{host}]" if ":" in host else host
        netloc = display_host
        if explicit_port is not None:
            netloc += f":{explicit_port}"
        return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))

    async def resolve(self, station: RadioStation, requester_id: int) -> ResolveResult:
        stream_url = await self.validate_url(station.url)
        loaded = await self._backend.load_tracks(stream_url)
        if not loaded.tracks:
            raise MediaUnavailableError(
                "That radio station is offline or its saved URL is not a direct audio stream."
            )
        source_track = loaded.tracks[0]
        track = replace(
            source_track,
            title=station.name,
            author="Live radio",
            uri=stream_url,
            source=Source.RADIO,
            duration_ms=None,
            artwork_url=None,
            is_stream=True,
            is_seekable=False,
            requested_by=requester_id,
        )
        return ResolveResult((track,))
