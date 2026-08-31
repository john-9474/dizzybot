from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import discord

from dizzybot.defaults.controls import DefaultPlaybackControls, PlaybackControlView
from dizzybot.defaults.permissions import DefaultPermissionPolicy
from dizzybot.defaults.player import DefaultGuildPlayer, DefaultPlayerManager
from dizzybot.defaults.queue import DefaultQueue
from dizzybot.domain import ResolveResult
from tests.fakes import FakeAudioBackend, FakePresenter, FakeSettingsRepository, make_track


class Message:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.deleted = False

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)

    async def delete(self) -> None:
        self.deleted = True


class Channel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.messages: list[tuple[Message, dict[str, Any]]] = []

    async def send(self, **kwargs: Any) -> Message:
        message = Message()
        self.messages.append((message, kwargs))
        return message


class Response:
    def __init__(self) -> None:
        self.done = False

    def is_done(self) -> bool:
        return self.done

    async def defer(self) -> None:
        self.done = True


class Followup:
    async def send(self, **kwargs: Any) -> None:
        del kwargs


def interaction(*, channel_id: int = 22) -> SimpleNamespace:
    voice_channel = SimpleNamespace(id=channel_id)
    return SimpleNamespace(
        guild_id=1,
        guild=SimpleNamespace(),
        user=SimpleNamespace(
            voice=SimpleNamespace(channel=voice_channel),
            guild_permissions=SimpleNamespace(administrator=False, manage_guild=False),
            roles=[],
        ),
        response=Response(),
        followup=Followup(),
    )


def button(view: PlaybackControlView, custom_id: str) -> discord.ui.Button[Any]:
    return next(
        item
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.custom_id == custom_id
    )


async def test_playback_panel_buttons_control_player_and_disable_on_stop() -> None:
    text_channel = Channel(33)
    client = SimpleNamespace(
        get_channel=lambda channel_id: text_channel if channel_id == 33 else None
    )
    settings = FakeSettingsRepository()
    presenter = FakePresenter()
    controls = DefaultPlaybackControls(
        client,
        settings,
        DefaultPermissionPolicy(),
        presenter,
    )
    audio = FakeAudioBackend()
    players = DefaultPlayerManager(
        audio,
        settings,
        presenter,
        controls,
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=10,
    )
    player = await players.get_or_create(1)
    await player.connect(SimpleNamespace(id=22), 33)
    await player.enqueue(ResolveResult((make_track("first"), make_track("second"))), 33)

    assert len(text_channel.messages) == 1
    message, sent = text_channel.messages[0]
    view = sent["view"]
    assert isinstance(view, PlaybackControlView)
    assert [item.label for item in view.children if isinstance(item, discord.ui.Button)] == [
        "Previous",
        "Pause",
        "Skip",
        "Stop",
    ]
    assert button(view, "dizzybot:previous").disabled is True

    await button(view, "dizzybot:play-pause").callback(interaction())
    assert audio.paused[1] is True
    assert button(view, "dizzybot:play-pause").label == "Play"
    await button(view, "dizzybot:play-pause").callback(interaction())
    assert audio.paused[1] is False

    await button(view, "dizzybot:skip").callback(interaction())
    assert (await player.snapshot()).current == make_track("second")
    assert button(view, "dizzybot:previous").disabled is False
    await button(view, "dizzybot:previous").callback(interaction())
    assert (await player.snapshot()).current == make_track("first")

    await button(view, "dizzybot:stop").callback(interaction())
    assert (await player.snapshot()).current is None
    assert all(item.disabled for item in view.children if isinstance(item, discord.ui.Button))
    assert message.edits


async def test_playback_panel_rejects_wrong_voice_channel_and_replaces_channel() -> None:
    first_channel = Channel(33)
    second_channel = Channel(44)
    channels = {33: first_channel, 44: second_channel}
    presenter = FakePresenter()
    settings = FakeSettingsRepository()
    controls = DefaultPlaybackControls(
        SimpleNamespace(get_channel=channels.get),
        settings,
        DefaultPermissionPolicy(),
        presenter,
    )
    audio = FakeAudioBackend()
    players = DefaultPlayerManager(
        audio,
        settings,
        presenter,
        controls,
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=10,
    )
    player = await players.get_or_create(1)
    await player.connect(SimpleNamespace(id=22), 33)
    await player.enqueue(ResolveResult((make_track("first"),)), 33)

    await controls.handle(1, interaction(channel_id=99), "skip")
    assert presenter.responses[-1][2:] == (True, True)
    assert (await player.snapshot()).current is not None

    snapshot = await player.snapshot()
    await controls.update(1, 44, snapshot)
    assert len(second_channel.messages) == 1
    old_view = first_channel.messages[0][1]["view"]
    assert all(item.disabled for item in old_view.children if isinstance(item, discord.ui.Button))

    missing = interaction()
    missing.guild_id = 2
    await controls.handle(2, missing, "stop")
    assert presenter.responses[-1][0] == "Controls unavailable"


async def test_public_response_reposts_player_controls_when_enabled() -> None:
    text_channel = Channel(33)
    presenter = FakePresenter()
    settings = FakeSettingsRepository()
    controls = DefaultPlaybackControls(
        SimpleNamespace(get_channel=lambda _channel_id: text_channel),
        settings,
        DefaultPermissionPolicy(),
        presenter,
    )
    players = DefaultPlayerManager(
        FakeAudioBackend(),
        settings,
        presenter,
        controls,
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=10,
    )
    player = await players.get_or_create(1)
    await player.connect(SimpleNamespace(id=22), 33)
    await player.enqueue(ResolveResult((make_track("first"),)), 33)
    old_message = text_channel.messages[0][0]

    await players.repost_controls(1)

    assert old_message.deleted is True
    assert len(text_channel.messages) == 2
    assert text_channel.messages[-1][1]["embed"]["current"] == make_track("first")


async def test_player_control_reposting_can_be_disabled() -> None:
    text_channel = Channel(33)
    presenter = FakePresenter()
    settings = FakeSettingsRepository()
    controls = DefaultPlaybackControls(
        SimpleNamespace(get_channel=lambda _channel_id: text_channel),
        settings,
        DefaultPermissionPolicy(),
        presenter,
        repost_player_controls=False,
    )
    players = DefaultPlayerManager(
        FakeAudioBackend(),
        settings,
        presenter,
        controls,
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=10,
    )
    player = await players.get_or_create(1)
    await player.connect(SimpleNamespace(id=22), 33)
    await player.enqueue(ResolveResult((make_track("first"),)), 33)

    await players.repost_controls(1)

    assert len(text_channel.messages) == 1
    assert text_channel.messages[0][0].deleted is False
