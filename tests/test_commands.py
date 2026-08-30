from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import discord
import pytest

from dizzybot.config import BotConfig
from dizzybot.defaults.commands import (
    DefaultMusicCommands,
    DefaultSettingsCommands,
    parse_seek_position,
)
from dizzybot.defaults.permissions import DefaultPermissionPolicy
from dizzybot.defaults.player import DefaultGuildPlayer, DefaultPlayerManager
from dizzybot.defaults.queue import DefaultQueue
from dizzybot.defaults.resolver import DefaultTrackResolver
from dizzybot.domain import BackendLoadResult, GuildSettings, Source
from dizzybot.errors import InvalidRequestError, PermissionDeniedError
from tests.fakes import (
    FakeAudioBackend,
    FakePlaybackControls,
    FakePresenter,
    FakeSettingsRepository,
    make_track,
)


class Response:
    def __init__(self) -> None:
        self.deferred = False

    async def defer(self, **kwargs: Any) -> None:
        del kwargs
        self.deferred = True


def make_interaction() -> SimpleNamespace:
    channel = SimpleNamespace(id=22, name="Music")
    permissions = SimpleNamespace(administrator=False, manage_guild=True)
    user = SimpleNamespace(
        id=99,
        voice=SimpleNamespace(channel=channel),
        guild_permissions=permissions,
        roles=[],
    )
    return SimpleNamespace(
        guild_id=1,
        channel_id=33,
        guild=SimpleNamespace(),
        user=user,
        response=Response(),
    )


def make_music_cog() -> tuple[
    DefaultMusicCommands,
    FakeAudioBackend,
    DefaultPlayerManager,
    FakePresenter,
]:
    audio = FakeAudioBackend()
    settings = FakeSettingsRepository()
    presenter = FakePresenter()
    manager = DefaultPlayerManager(
        audio,
        settings,
        presenter,
        FakePlaybackControls(),
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=20,
    )
    cog = DefaultMusicCommands(
        DefaultTrackResolver(
            audio, available_sources={Source.YOUTUBE, Source.SOUNDCLOUD, Source.SPOTIFY}
        ),
        manager,
        settings,
        DefaultPermissionPolicy(),
        presenter,
        BotConfig(discord_token="token"),
    )
    return cog, audio, manager, presenter


@pytest.mark.parametrize(
    ("value", "expected"),
    [("90", 90_000), ("01:30", 90_000), ("1:01:01", 3_661_000)],
)
def test_parse_seek_position(value: str, expected: int) -> None:
    assert parse_seek_position(value) == expected


@pytest.mark.parametrize("value", ["", "-1", "1:99", "1:2:3:4", "words"])
def test_parse_seek_position_rejects_invalid_values(value: str) -> None:
    with pytest.raises(InvalidRequestError):
        parse_seek_position(value)


async def callback(command: Any, cog: Any, interaction: Any, *args: Any) -> None:
    await command.callback(cog, interaction, *args)


async def test_music_command_happy_path() -> None:
    cog, audio, manager, presenter = make_music_cog()
    interaction = make_interaction()
    await callback(cog.join, cog, interaction)
    assert audio.connected == {1: 22}

    audio.loaded = BackendLoadResult(
        (make_track("one"), make_track("two"), make_track("three")),
        playlist_name="Playlist",
    )
    await callback(cog.play, cog, interaction, "https://youtube.com/playlist?list=x", None)
    assert interaction.response.deferred is True
    assert "3" in presenter.responses[-1][1]
    await callback(cog.queue, cog, interaction, 1)
    await callback(cog.nowplaying, cog, interaction)
    await callback(cog.pause, cog, interaction)
    await callback(cog.resume, cog, interaction)
    await callback(cog.volume, cog, interaction, 50)
    await callback(cog.seek, cog, interaction, "00:10")
    repeat_choice = SimpleNamespace(value="queue")
    await callback(cog.repeat, cog, interaction, repeat_choice)
    await callback(cog.move, cog, interaction, 2, 1)
    await callback(cog.remove, cog, interaction, 2)

    audio.loaded = BackendLoadResult((make_track("four"), make_track("five")), "More")
    await callback(cog.play, cog, interaction, "https://youtube.com/playlist?list=y", None)
    await callback(cog.shuffle, cog, interaction)
    await callback(cog.clear, cog, interaction)
    await callback(cog.skip, cog, interaction)
    player = manager.get(1)
    assert player is not None
    if (await player.snapshot()).current is not None:
        await callback(cog.stop, cog, interaction)
    await callback(cog.leave, cog, interaction)
    assert player.is_connected() is False


async def test_join_when_connected_and_command_registration() -> None:
    cog, _, _, presenter = make_music_cog()
    interaction = make_interaction()
    await callback(cog.join, cog, interaction)
    await callback(cog.join, cog, interaction)
    assert presenter.responses[-1][1] == "Already connected to voice."
    added: list[Any] = []

    async def add_cog(value: Any) -> None:
        added.append(value)

    await cog.register(SimpleNamespace(add_cog=add_cog))
    assert added == [cog]


async def test_settings_commands_update_and_reset() -> None:
    settings = FakeSettingsRepository()
    audio = FakeAudioBackend()
    presenter = FakePresenter()
    manager = DefaultPlayerManager(
        audio,
        settings,
        presenter,
        FakePlaybackControls(),
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=20,
    )
    cog = DefaultSettingsCommands(
        settings,
        manager,
        DefaultPermissionPolicy(),
        presenter,
        {Source.YOUTUBE, Source.SOUNDCLOUD, Source.SPOTIFY},
    )
    interaction = make_interaction()
    await callback(cog.show, cog, interaction)
    await callback(cog.volume, cog, interaction, 60)
    await callback(cog.idle_timeout, cog, interaction, 45)
    await callback(cog.dj_role, cog, interaction, SimpleNamespace(id=7, mention="@DJ"))
    interaction.user.roles.append(SimpleNamespace(id=7))
    await callback(cog.twenty_four_seven, cog, interaction, True)
    await callback(
        cog.search_provider, cog, interaction, SimpleNamespace(value=Source.SPOTIFY.value)
    )
    current = await settings.get(1)
    assert current == GuildSettings(
        guild_id=1,
        default_volume=60,
        idle_timeout_seconds=45,
        stay_connected=True,
        dj_role_id=7,
        default_search_source=Source.SPOTIFY,
    )
    await callback(cog.reset, cog, interaction)
    assert await settings.get(1) == GuildSettings(guild_id=1)

    added: list[Any] = []

    async def add_cog(value: Any) -> None:
        added.append(value)

    await cog.register(SimpleNamespace(add_cog=add_cog))
    assert added == [cog]


async def test_24_7_setting_requires_configured_dj_role() -> None:
    settings = FakeSettingsRepository(GuildSettings(guild_id=0, dj_role_id=7))
    manager = DefaultPlayerManager(
        FakeAudioBackend(),
        settings,
        FakePresenter(),
        FakePlaybackControls(),
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=20,
    )
    cog = DefaultSettingsCommands(
        settings,
        manager,
        DefaultPermissionPolicy(),
        FakePresenter(),
        {Source.YOUTUBE},
    )
    interaction = make_interaction()

    with pytest.raises(InvalidRequestError):
        await callback(cog.idle_timeout, cog, interaction, 10)
    with pytest.raises(PermissionDeniedError, match="DJ role"):
        await callback(cog.twenty_four_seven, cog, interaction, True)

    interaction.user.roles.append(SimpleNamespace(id=7))
    await callback(cog.twenty_four_seven, cog, interaction, True)
    assert (await settings.get(1)).stay_connected is True


async def test_command_error_handler_presents_expected_and_unexpected_errors() -> None:
    cog, _, _, presenter = make_music_cog()
    interaction = make_interaction()
    await cog.cog_app_command_error(interaction, InvalidRequestError("bad"))
    assert presenter.responses[-1][2:] == (True, True)
    await cog.cog_app_command_error(interaction, RuntimeError("boom"))
    assert presenter.responses[-1][0] == "Unexpected error"


def test_music_commands_do_not_request_message_content_intent() -> None:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.voice_states = True
    assert intents.message_content is False
