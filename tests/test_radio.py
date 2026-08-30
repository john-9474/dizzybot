from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dizzybot.contracts import BaseRadioRepository, BaseRadioResolver
from dizzybot.defaults.permissions import DefaultPermissionPolicy
from dizzybot.defaults.player import DefaultGuildPlayer, DefaultPlayerManager
from dizzybot.defaults.queue import DefaultQueue
from dizzybot.defaults.radio import DefaultRadioResolver
from dizzybot.defaults.radio_commands import DefaultRadioCommands
from dizzybot.defaults.radio_repository import DefaultRadioRepository
from dizzybot.domain import GuildSettings, RadioStation, ResolveResult, Source
from dizzybot.errors import InvalidRequestError, PermissionDeniedError
from tests.fakes import (
    FakeAudioBackend,
    FakePlaybackControls,
    FakePresenter,
    FakeSettingsRepository,
    make_track,
)


async def public_dns(_host: str, _port: int) -> tuple[str, ...]:
    return ("1.1.1.1",)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://streaming.radio.co/s06bd9d805/listen",
            "https://streaming.radio.co/s06bd9d805/listen",
        ),
        (
            "https://s2.ssl-stream.com/listen/uk_bass_radio/stream",
            "https://s2.ssl-stream.com/listen/uk_bass_radio/stream",
        ),
        ("http://94.130.242.5:8010/stream", "http://94.130.242.5:8010/stream"),
        ("http://94.130.242.5:8004/stream", "http://94.130.242.5:8004/stream"),
        ("http://94.130.242.5:8046/stream", "http://94.130.242.5:8046/stream"),
    ],
)
async def test_radio_url_validation_accepts_direct_public_streams(url: str, expected: str) -> None:
    resolver = DefaultRadioResolver(FakeAudioBackend(), address_resolver=public_dns)
    assert await resolver.validate_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "ftp://radio.example/stream",
        "http://user:password@radio.example/stream",
        "http://127.0.0.1:8000/stream",
        "http://192.168.1.20/stream",
        "not a url",
    ],
)
async def test_radio_url_validation_rejects_unsafe_urls(url: str) -> None:
    resolver = DefaultRadioResolver(FakeAudioBackend(), address_resolver=public_dns)
    with pytest.raises(InvalidRequestError):
        await resolver.validate_url(url)


async def test_private_radio_urls_require_explicit_opt_in() -> None:
    resolver = DefaultRadioResolver(FakeAudioBackend(), allow_private_networks=True)
    assert await resolver.validate_url("http://192.168.1.20:8000/stream") == (
        "http://192.168.1.20:8000/stream"
    )


async def test_radio_resolver_normalizes_loaded_track_as_live() -> None:
    backend = FakeAudioBackend()
    backend.loaded = backend.loaded.__class__((make_track("station-a"),))
    resolver = DefaultRadioResolver(backend, address_resolver=public_dns)
    station = RadioStation(1, "House Nation", "https://radio.example/stream")

    result = await resolver.resolve(station, 42)

    track = result.tracks[0]
    assert track.title == "House Nation"
    assert track.author == "Live radio"
    assert track.source is Source.RADIO
    assert track.is_stream is True
    assert track.is_seekable is False
    assert track.requested_by == 42


async def test_sqlite_radio_stations_persist_per_guild(tmp_path: Path) -> None:
    database = tmp_path / "radio.sqlite3"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    repository = DefaultRadioRepository(url)
    await repository.start()
    assert await repository.list(1) == ()
    station = await repository.add(RadioStation(1, "  UK   Bass  ", "https://radio/stream"))
    assert station.name == "UK Bass"
    assert await repository.get(1, "uk bass") == station
    assert await repository.get(2, "UK Bass") is None
    with pytest.raises(InvalidRequestError, match="already exists"):
        await repository.add(RadioStation(1, "UK BASS", "https://other/stream"))
    await repository.close()

    reopened = DefaultRadioRepository(url)
    await reopened.start()
    assert await reopened.list(1) == (station,)
    assert await reopened.remove(1, "uk bass") == station
    assert await reopened.list(1) == ()
    await reopened.close()


class FakeRadioRepository(BaseRadioRepository):
    def __init__(self) -> None:
        self.rows: dict[tuple[int, str], RadioStation] = {}

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def is_ready(self) -> bool:
        return True

    async def add(self, station: RadioStation) -> RadioStation:
        self.rows[(station.guild_id, station.name.casefold())] = station
        return station

    async def get(self, guild_id: int, name: str) -> RadioStation | None:
        return self.rows.get((guild_id, name.casefold()))

    async def list(self, guild_id: int) -> tuple[RadioStation, ...]:
        return tuple(station for station in self.rows.values() if station.guild_id == guild_id)

    async def remove(self, guild_id: int, name: str) -> RadioStation | None:
        return self.rows.pop((guild_id, name.casefold()), None)


class FakeRadioResolver(BaseRadioResolver):
    async def validate_url(self, url: str) -> str:
        return url

    async def resolve(self, station: RadioStation, requester_id: int) -> ResolveResult:
        track = replace(
            make_track("radio", source=Source.RADIO, stream=True, seekable=False),
            title=station.name,
            uri=station.url,
            requested_by=requester_id,
        )
        return ResolveResult((track,))


class Response:
    def __init__(self) -> None:
        self.deferred = False

    async def defer(self, **kwargs: Any) -> None:
        del kwargs
        self.deferred = True


def interaction(*, administrator: bool) -> SimpleNamespace:
    channel = SimpleNamespace(id=22, name="Music")
    return SimpleNamespace(
        guild_id=1,
        channel_id=33,
        guild=SimpleNamespace(),
        user=SimpleNamespace(
            id=99,
            voice=SimpleNamespace(channel=channel),
            guild_permissions=SimpleNamespace(administrator=administrator, manage_guild=False),
            roles=[],
        ),
        response=Response(),
    )


async def callback(command: Any, cog: Any, command_interaction: Any, *args: Any) -> None:
    await command.callback(cog, command_interaction, *args)


async def test_radio_commands_add_list_play_and_remove() -> None:
    repository = FakeRadioRepository()
    settings = FakeSettingsRepository()
    audio = FakeAudioBackend()
    presenter = FakePresenter()
    players = DefaultPlayerManager(
        audio,
        settings,
        presenter,
        FakePlaybackControls(),
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=20,
    )
    cog = DefaultRadioCommands(
        FakeRadioResolver(),
        repository,
        players,
        settings,
        DefaultPermissionPolicy(),
        presenter,
        station_limit=10,
    )
    command_interaction = interaction(administrator=True)

    await callback(
        cog.add,
        cog,
        command_interaction,
        "House Nation",
        "https://streaming.radio.co/s06bd9d805/listen",
    )
    await callback(cog.list_stations, cog, command_interaction, 1)
    await callback(cog.play, cog, command_interaction, "house nation")
    assert audio.connected == {1: 22}
    assert audio.played[-1][1].source is Source.RADIO
    assert audio.played[-1][1].is_stream is True
    await callback(cog.remove, cog, command_interaction, "House Nation")
    assert await repository.list(1) == ()


async def test_radio_management_requires_dj_or_administrator() -> None:
    repository = FakeRadioRepository()
    settings = FakeSettingsRepository(GuildSettings(guild_id=0, dj_role_id=7))
    presenter = FakePresenter()
    players = DefaultPlayerManager(
        FakeAudioBackend(),
        settings,
        presenter,
        FakePlaybackControls(),
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=20,
    )
    cog = DefaultRadioCommands(
        FakeRadioResolver(),
        repository,
        players,
        settings,
        DefaultPermissionPolicy(),
        presenter,
        station_limit=1,
    )
    command_interaction = interaction(administrator=False)
    with pytest.raises(PermissionDeniedError, match="DJ role"):
        await callback(cog.add, cog, command_interaction, "Station", "https://radio/stream")

    command_interaction.user.roles.append(SimpleNamespace(id=7))
    await callback(cog.add, cog, command_interaction, "Station", "https://radio/stream")
    with pytest.raises(InvalidRequestError, match="limit"):
        await callback(cog.add, cog, command_interaction, "Second", "https://radio/two")
