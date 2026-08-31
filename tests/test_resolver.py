import pytest

from dizzybot.defaults.resolver import DefaultTrackResolver
from dizzybot.domain import BackendLoadResult, ResolveRequest, Source
from dizzybot.errors import InvalidRequestError, MediaUnavailableError, SourceUnavailableError
from tests.fakes import FakeAudioBackend, make_track

ALL_SOURCES = frozenset(
    {
        Source.YOUTUBE,
        Source.SOUNDCLOUD,
        Source.SPOTIFY,
        Source.APPLE_MUSIC,
        Source.TIDAL,
        Source.BANDCAMP,
    }
)


@pytest.mark.parametrize(
    ("url", "source"),
    [
        ("https://youtu.be/id", Source.YOUTUBE),
        ("https://music.youtube.com/watch?v=id", Source.YOUTUBE),
        ("https://soundcloud.com/a/b", Source.SOUNDCLOUD),
        ("https://open.spotify.com/track/id", Source.SPOTIFY),
        ("https://music.apple.com/gb/album/name/id", Source.APPLE_MUSIC),
        ("https://listen.tidal.com/album/id", Source.TIDAL),
        ("https://artist.bandcamp.com/track/name", Source.BANDCAMP),
        ("words", None),
    ],
)
def test_detect_source(url: str, source: Source | None) -> None:
    assert (
        DefaultTrackResolver(FakeAudioBackend(), available_sources=ALL_SOURCES).detect_source(url)
        is source
    )


async def test_search_uses_prefix_and_only_first_result() -> None:
    backend = FakeAudioBackend()
    backend.loaded = BackendLoadResult((make_track("first"), make_track("second")))
    resolver = DefaultTrackResolver(backend, available_sources=ALL_SOURCES)
    captured: list[str] = []

    async def load(identifier: str) -> BackendLoadResult:
        captured.append(identifier)
        return backend.loaded

    backend.load_tracks = load
    result = await resolver.resolve(
        ResolveRequest("query", Source.AUTO, 42, 100, Source.SOUNDCLOUD)
    )
    assert captured == ["scsearch:query"]
    assert [track.identifier for track in result.tracks] == ["first"]
    assert result.tracks[0].requested_by == 42


@pytest.mark.parametrize(
    ("source", "prefix"),
    [
        (Source.SPOTIFY, "spsearch:"),
        (Source.APPLE_MUSIC, "amsearch:"),
        (Source.TIDAL, "tdsearch:"),
        (Source.BANDCAMP, "bcsearch:"),
    ],
)
async def test_provider_search_prefixes(source: Source, prefix: str) -> None:
    backend = FakeAudioBackend()
    resolver = DefaultTrackResolver(backend, available_sources=ALL_SOURCES)
    captured: list[str] = []

    async def load(identifier: str) -> BackendLoadResult:
        captured.append(identifier)
        return BackendLoadResult((make_track(),))

    backend.load_tracks = load
    await resolver.resolve(ResolveRequest("query", source, 1, 10))
    assert captured == [f"{prefix}query"]


async def test_playlist_filters_streams_and_caps_result() -> None:
    backend = FakeAudioBackend()
    backend.loaded = BackendLoadResult(
        (make_track("one"), make_track("live", stream=True), make_track("three")),
        playlist_name="A list",
    )
    resolver = DefaultTrackResolver(backend, available_sources=ALL_SOURCES)
    result = await resolver.resolve(
        ResolveRequest("https://youtube.com/playlist?list=x", Source.AUTO, 7, 1)
    )
    assert result.playlist is not None
    assert result.playlist.name == "A list"
    assert [track.identifier for track in result.tracks] == ["one"]
    assert result.tracks[0].playlist_name == "A list"
    assert result.tracks[0].playlist_position == 1
    assert result.tracks[0].playlist_size == 1
    assert result.skipped_count == 2
    assert result.truncated is True


async def test_resolver_reports_source_and_media_errors() -> None:
    backend = FakeAudioBackend()
    resolver = DefaultTrackResolver(backend, available_sources={Source.YOUTUBE, Source.SOUNDCLOUD})
    with pytest.raises(SourceUnavailableError):
        await resolver.resolve(ResolveRequest("song", Source.SPOTIFY, 1, 10))
    with pytest.raises(SourceUnavailableError, match="TIDAL_TOKEN"):
        await resolver.resolve(ResolveRequest("song", Source.TIDAL, 1, 10))
    with pytest.raises(InvalidRequestError, match="radio play"):
        await resolver.resolve(ResolveRequest("station", Source.RADIO, 1, 10))
    with pytest.raises(InvalidRequestError, match="Only YouTube"):
        await resolver.resolve(ResolveRequest("https://example.com/song", Source.AUTO, 1, 10))
    with pytest.raises(InvalidRequestError, match="not youtube"):
        await resolver.resolve(
            ResolveRequest("https://open.spotify.com/track/x", Source.YOUTUBE, 1, 10)
        )
    with pytest.raises(InvalidRequestError, match="required"):
        await resolver.resolve(ResolveRequest("  ", Source.AUTO, 1, 10))

    backend.loaded = BackendLoadResult((make_track("live", stream=True),))
    with pytest.raises(MediaUnavailableError):
        await DefaultTrackResolver(backend, available_sources=ALL_SOURCES).resolve(
            ResolveRequest("live", Source.YOUTUBE, 1, 10)
        )
