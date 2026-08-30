import pytest

from dizzybot.defaults.queue import DefaultQueue
from dizzybot.domain import PlaybackEndReason, RepeatMode
from dizzybot.errors import InvalidRequestError
from tests.fakes import make_track


def test_queue_order_move_remove_clear_and_reset() -> None:
    queue = DefaultQueue()
    tracks = tuple(make_track(str(index)) for index in range(1, 5))
    queue.enqueue(tracks)
    assert queue.take_next() == tracks[0]
    assert queue.take_next() == tracks[0]
    assert queue.move(3, 1) == tracks[3]
    assert queue.upcoming() == (tracks[3], tracks[1], tracks[2])
    assert queue.remove(2) == tracks[1]
    assert queue.clear_upcoming() == 2
    queue.set_repeat_mode(RepeatMode.QUEUE)
    queue.reset()
    assert queue.current is None
    assert queue.upcoming() == ()
    assert queue.repeat_mode is RepeatMode.OFF


def test_stop_clears_playback_but_preserves_repeat_setting() -> None:
    queue = DefaultQueue()
    queue.enqueue((make_track(),))
    queue.take_next()
    queue.set_repeat_mode(RepeatMode.QUEUE)
    queue.stop()
    assert queue.current is None
    assert queue.upcoming() == ()
    assert queue.total_size == 0
    assert queue.repeat_mode is RepeatMode.QUEUE


@pytest.mark.parametrize("mode", [RepeatMode.OFF, RepeatMode.TRACK, RepeatMode.QUEUE])
def test_natural_completion_honours_repeat(mode: RepeatMode) -> None:
    queue = DefaultQueue()
    first, second = make_track("first"), make_track("second")
    queue.enqueue((first, second))
    queue.take_next()
    queue.set_repeat_mode(mode)
    queue.complete_current(PlaybackEndReason.FINISHED)
    expected = first if mode is RepeatMode.TRACK else second
    assert queue.take_next() == expected
    if mode is RepeatMode.QUEUE:
        assert queue.upcoming() == (first,)


def test_skip_never_repeats_and_invalid_positions_fail() -> None:
    queue = DefaultQueue()
    first, second = make_track("first"), make_track("second")
    queue.enqueue((first, second))
    queue.take_next()
    queue.set_repeat_mode(RepeatMode.TRACK)
    queue.complete_current(PlaybackEndReason.SKIPPED)
    assert queue.take_next() == second
    with pytest.raises(InvalidRequestError):
        queue.remove(0)
    with pytest.raises(InvalidRequestError):
        queue.move(1, 3)


def test_shuffle_preserves_all_tracks(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = DefaultQueue()
    tracks = tuple(make_track(str(index)) for index in range(4))
    queue.enqueue(tracks)
    monkeypatch.setattr("random.shuffle", lambda values: values.reverse())
    queue.shuffle()
    assert queue.upcoming() == tuple(reversed(tracks))


def test_previous_and_queue_progress() -> None:
    queue = DefaultQueue()
    first, second, third = make_track("first"), make_track("second"), make_track("third")
    queue.enqueue((first, second, third))
    assert queue.total_size == 3
    assert queue.take_next() == first
    assert queue.current_position == 1
    assert queue.can_go_previous is False

    queue.complete_current(PlaybackEndReason.SKIPPED)
    assert queue.take_next() == second
    assert queue.current_position == 2
    assert queue.can_go_previous is True
    assert queue.take_previous() == first
    assert queue.current_position == 1
    assert queue.upcoming() == (second, third)

    assert queue.remove(2) == third
    assert queue.total_size == 2
    assert queue.clear_upcoming() == 1
    assert queue.total_size == 1


def test_previous_with_repeat_queue_does_not_duplicate_track() -> None:
    queue = DefaultQueue()
    first, second = make_track("first"), make_track("second")
    queue.enqueue((first, second))
    queue.set_repeat_mode(RepeatMode.QUEUE)
    queue.take_next()
    queue.complete_current(PlaybackEndReason.FINISHED)
    assert queue.take_next() == second
    assert queue.current_position == 2
    assert queue.take_previous() == first
    assert queue.current_position == 1
    assert queue.upcoming() == (second,)


def test_failed_track_is_not_available_as_previous() -> None:
    queue = DefaultQueue()
    failed, good = make_track("failed"), make_track("good")
    queue.enqueue((failed, good))
    queue.take_next()
    queue.complete_current(PlaybackEndReason.LOAD_FAILED)
    assert queue.take_next() == good
    assert queue.total_size == 1
    assert queue.current_position == 1
    with pytest.raises(InvalidRequestError, match="no previous"):
        queue.take_previous()
