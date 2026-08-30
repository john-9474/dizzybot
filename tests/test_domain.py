from dizzybot.domain import ResolveResult
from dizzybot.errors import DizzyBotError
from tests.fakes import make_track


def test_domain_helpers_and_default_error() -> None:
    track = make_track()
    assert track.duration_seconds == 180
    assert make_track(stream=True).duration_seconds is None
    assert ResolveResult((track,)).is_playlist is False
    assert str(DizzyBotError()) == DizzyBotError.default_message
