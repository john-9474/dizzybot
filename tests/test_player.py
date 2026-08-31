from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dizzybot.defaults.player import DefaultGuildPlayer, DefaultPlayerManager
from dizzybot.defaults.queue import DefaultQueue
from dizzybot.domain import (
    GuildSettings,
    PlaybackEndReason,
    RepeatMode,
    ResolveResult,
)
from dizzybot.errors import InvalidRequestError, PlayerStateError, QueueLimitError
from tests.fakes import (
    FakeAudioBackend,
    FakePlaybackControls,
    FakePresenter,
    FakeSettingsRepository,
    make_track,
)


def make_player(
    *,
    queue_limit: int = 10,
    idle_timeout: int = 300,
    stay_connected: bool = False,
) -> tuple[DefaultGuildPlayer, FakeAudioBackend, FakePresenter]:
    audio = FakeAudioBackend()
    presenter = FakePresenter()
    player = DefaultGuildPlayer(
        1,
        audio,
        DefaultQueue(),
        presenter,
        FakePlaybackControls(),
        GuildSettings(
            guild_id=1,
            idle_timeout_seconds=idle_timeout,
            stay_connected=stay_connected,
        ),
        queue_limit=queue_limit,
    )
    return player, audio, presenter


async def connect(player: DefaultGuildPlayer) -> None:
    await player.connect(SimpleNamespace(id=22), 33)


async def test_player_enqueues_advances_and_isolates_state() -> None:
    player, audio, _ = make_player()
    await connect(player)
    first, second = make_track("first"), make_track("second")
    assert await player.enqueue(ResolveResult((first, second)), 33) == 2
    assert [call[1] for call in audio.played] == [first]
    await player.handle_track_end(PlaybackEndReason.FINISHED, first.backend_key)
    assert [call[1] for call in audio.played] == [first, second]
    snapshot = await player.snapshot()
    assert snapshot.current == second
    assert snapshot.upcoming == ()


async def test_skip_stop_clear_move_shuffle_repeat_and_leave() -> None:
    player, audio, _ = make_player()
    await connect(player)
    tracks = tuple(make_track(str(index)) for index in range(5))
    await player.enqueue(ResolveResult(tracks), 33)
    moved = await player.move(4, 1)
    assert moved == tracks[4]
    removed = await player.remove(2)
    assert removed == tracks[1]
    await player.set_repeat(RepeatMode.TRACK)
    skipped = await player.skip()
    assert skipped == tracks[0]
    assert audio.stopped == [1]
    await player.shuffle()
    assert await player.clear() == 2
    await player.stop()
    assert (await player.snapshot()).current is None
    await player.leave()
    assert player.is_connected() is False


async def test_player_controls_and_validation() -> None:
    player, audio, _ = make_player()
    with pytest.raises(PlayerStateError):
        await player.pause()
    await connect(player)
    track = make_track("track")
    await player.enqueue(ResolveResult((track,)), 33)
    await player.pause()
    assert audio.paused[1] is True
    with pytest.raises(PlayerStateError, match="already paused"):
        await player.pause()
    await player.resume()
    assert audio.paused[1] is False
    with pytest.raises(PlayerStateError, match="not paused"):
        await player.resume()
    await player.set_volume(0)
    await player.set_volume(100)
    assert audio.volumes[1] == 100
    with pytest.raises(InvalidRequestError):
        await player.set_volume(101)
    await player.seek(10_000)
    assert audio.positions[1] == 10_000
    with pytest.raises(InvalidRequestError):
        await player.seek(180_000)


async def test_player_rejects_unseekable_and_queue_overflow() -> None:
    player, _, _ = make_player(queue_limit=1)
    await connect(player)
    with pytest.raises(QueueLimitError):
        await player.enqueue(ResolveResult((make_track("one"), make_track("two"))), 33)
    await player.enqueue(ResolveResult((make_track("one", seekable=False),)), 33)
    with pytest.raises(PlayerStateError, match="cannot be seeked"):
        await player.seek(1)


async def test_failed_tracks_notify_and_continue() -> None:
    player, audio, presenter = make_player()
    await connect(player)
    bad, good = make_track("bad", title="Bad"), make_track("good")
    audio.fail_titles.add("Bad")
    await player.enqueue(ResolveResult((bad, good)), 33)
    assert (await player.snapshot()).current == good
    assert presenter.notifications[0][1] == "Track failed"
    await player.handle_track_end(PlaybackEndReason.STUCK, good.backend_key)
    assert presenter.notifications[-1][1] == "Playback error"


async def test_ignored_backend_event_does_not_skip_new_track() -> None:
    player, _, _ = make_player()
    await connect(player)
    first, second = make_track("first"), make_track("second")
    await player.enqueue(ResolveResult((first, second)), 33)
    await player.skip()
    await player.handle_track_end(PlaybackEndReason.REPLACED, first.backend_key)
    assert (await player.snapshot()).current == second


async def test_previous_replays_history_and_restores_interrupted_track() -> None:
    player, audio, _ = make_player()
    await connect(player)
    first, second = make_track("first"), make_track("second")
    await player.enqueue(ResolveResult((first, second)), 33)
    await player.skip()
    assert (await player.snapshot()).current == second

    assert await player.previous() == first
    snapshot = await player.snapshot()
    assert snapshot.current == first
    assert snapshot.upcoming == (second,)
    assert snapshot.queue_position == 1
    assert snapshot.queue_total == 2
    assert audio.played[-1][1] == first


async def test_unavailable_previous_does_not_ignore_natural_track_end() -> None:
    player, _, _ = make_player()
    await connect(player)
    track = make_track("only")
    await player.enqueue(ResolveResult((track,)), 33)
    with pytest.raises(InvalidRequestError, match="no previous"):
        await player.previous()
    await player.handle_track_end(PlaybackEndReason.FINISHED, track.backend_key)
    assert (await player.snapshot()).current is None


async def test_idle_disconnects_empty_or_humanless_player() -> None:
    player, _, presenter = make_player(idle_timeout=0)
    await connect(player)
    await asyncio.sleep(0.01)
    assert player.is_connected() is False
    assert presenter.notifications[-1][1] == "Disconnected"

    player, _, _ = make_player(idle_timeout=0)
    await connect(player)
    await player.enqueue(ResolveResult((make_track(),)), 33)
    await player.update_human_presence(False)
    await asyncio.sleep(0.01)
    assert player.is_connected() is False


async def test_reconnect_resets_stale_empty_channel_presence_for_radio() -> None:
    player, _, presenter = make_player(idle_timeout=0)
    human = SimpleNamespace(bot=False)
    channel = SimpleNamespace(id=22, members=[human])

    await player.connect(channel, 33)
    await player.enqueue(ResolveResult((make_track(),)), 33)
    await player.update_human_presence(False)
    await asyncio.sleep(0.01)
    assert player.is_connected() is False

    await player.connect(channel, 33)
    radio = make_track("radio", stream=True, seekable=False)
    await player.enqueue(ResolveResult((radio,)), 33)
    await asyncio.sleep(0.01)

    assert player.is_connected() is True
    assert (await player.snapshot()).current == radio
    assert len(presenter.notifications) == 1


async def test_24_7_mode_suppresses_and_restores_empty_channel_timeout() -> None:
    player, _, presenter = make_player(idle_timeout=0, stay_connected=True)
    await connect(player)
    await player.update_human_presence(False)
    await asyncio.sleep(0.01)
    assert player.is_connected() is True

    await player.update_settings(
        GuildSettings(guild_id=1, idle_timeout_seconds=0, stay_connected=False)
    )
    await asyncio.sleep(0.01)
    assert player.is_connected() is False
    assert presenter.notifications[-1][1] == "Disconnected"


async def test_player_manager_creation_routing_settings_and_close() -> None:
    audio = FakeAudioBackend()
    settings = FakeSettingsRepository(GuildSettings(guild_id=0, default_volume=55))
    presenter = FakePresenter()
    manager = DefaultPlayerManager(
        audio,
        settings,
        presenter,
        FakePlaybackControls(),
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=5,
    )
    first, same, other = await asyncio.gather(
        manager.get_or_create(1), manager.get_or_create(1), manager.get_or_create(2)
    )
    assert first is same
    assert first is not other
    await first.connect(SimpleNamespace(id=10), 20)
    track = make_track()
    await first.enqueue(ResolveResult((track,)), 20)
    await audio.emit(1, PlaybackEndReason.FINISHED, track.backend_key)
    assert (await first.snapshot()).current is None
    assert manager.get(999) is None
    await manager.close()
    assert first.is_connected() is False
