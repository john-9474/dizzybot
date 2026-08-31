from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from dizzybot.defaults.presenter import DefaultPresenter, PaginationView, format_duration
from dizzybot.domain import QueueSnapshot, RepeatMode
from dizzybot.errors import InvalidRequestError
from tests.fakes import make_track


class Sender:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


class Response(Sender):
    def __init__(self, done: bool) -> None:
        super().__init__()
        self.done = done

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, **kwargs: Any) -> None:
        await self.send(**kwargs)

    async def edit_message(self, **kwargs: Any) -> None:
        await self.send(**kwargs)


class ExpiredResponse(Response):
    async def send_message(self, **kwargs: Any) -> None:
        del kwargs
        response = SimpleNamespace(status=404, reason="Not Found")
        raise discord.NotFound(response, {"code": 10062, "message": "Unknown interaction"})


def pagination_button(view: PaginationView, custom_id: str) -> discord.ui.Button[Any]:
    return next(
        item
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.custom_id == custom_id
    )


def test_duration_and_queue_pages() -> None:
    assert format_duration(None) == "unknown"
    assert format_duration(65_000) == "1:05"
    assert format_duration(3_665_000) == "1:01:05"
    presenter = DefaultPresenter()
    tracks = tuple(make_track(str(index)) for index in range(12))
    snapshot = QueueSnapshot(tracks[0], tracks[1:], RepeatMode.QUEUE, 75, False)
    title, description = presenter.queue_page(snapshot, 2)
    assert title == "Queue — page 2/2"
    assert "`11.`" in description
    assert "Repeat: `queue`" in description
    with pytest.raises(InvalidRequestError):
        presenter.queue_page(snapshot, 3)


def test_now_playing_embed_includes_playlist_queue_and_playback_details() -> None:
    presenter = DefaultPresenter()
    track = replace(
        make_track("song"),
        requested_by=42,
        artwork_url="https://example.com/cover.jpg",
        playlist_name="The Playlist",
        playlist_position=3,
        playlist_size=12,
    )
    snapshot = QueueSnapshot(
        track,
        (),
        RepeatMode.OFF,
        75,
        False,
        position_ms=65_000,
        queue_position=4,
        queue_total=10,
    )

    embed = presenter.now_playing_embed(snapshot)

    fields = {field.name: field.value for field in embed.fields}
    assert embed.title == "Now playing"
    assert fields["Playback"] == "1:05 / 3:00"
    assert fields["Queue position"] == "4 of 10"
    assert "track 3 of 12" in fields["Playlist"]
    assert fields["Requested by"] == "<@42>"
    assert embed.thumbnail.url == "https://example.com/cover.jpg"


def test_now_playing_embed_handles_paused_live_stream() -> None:
    presenter = DefaultPresenter()
    snapshot = QueueSnapshot(make_track(stream=True), (), RepeatMode.OFF, 75, True)
    embed = presenter.now_playing_embed(snapshot)
    fields = {field.name: field.value for field in embed.fields}
    assert embed.title == "Paused"
    assert fields["Playback"] == "Live stream"
    assert fields["Queue position"] == "Not available"


async def test_presenter_initial_followup_and_notification() -> None:
    presenter = DefaultPresenter()
    initial = SimpleNamespace(response=Response(False), followup=Sender())
    await presenter.respond(initial, "Title", "Body", error=True, ephemeral=True)
    assert initial.response.messages[0]["ephemeral"] is True
    followup = SimpleNamespace(response=Response(True), followup=Sender())
    await presenter.respond(followup, "Title", "Body")
    assert followup.followup.messages
    assert "view" not in followup.followup.messages[0]

    channel = Sender()
    presenter.attach(
        SimpleNamespace(get_channel=lambda channel_id: channel if channel_id == 1 else None)
    )
    await presenter.notify(1, "Notice", "Body")
    await presenter.notify(2, "Ignored", "Body")
    assert len(channel.messages) == 1


async def test_presenter_runs_repost_handler_only_for_public_successes() -> None:
    presenter = DefaultPresenter()
    reposted: list[int] = []

    async def repost(guild_id: int) -> None:
        reposted.append(guild_id)

    presenter.set_public_response_handler(repost)
    interaction = SimpleNamespace(
        guild_id=9,
        user=SimpleNamespace(id=42),
        response=Response(False),
        followup=Sender(),
    )

    await presenter.respond(interaction, "Public", "Body")
    await presenter.respond(interaction, "Private", "Body", ephemeral=True)
    await presenter.respond(interaction, "Error", "Body", error=True)

    assert reposted == [9]


async def test_paginated_response_moves_between_pages_and_restricts_owner() -> None:
    presenter = DefaultPresenter()
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42),
        response=Response(False),
        followup=Sender(),
    )
    await presenter.respond_paginated(
        interaction,
        (("Page 1/2", "First"), ("Page 2/2", "Second")),
    )

    sent = interaction.response.messages[0]
    view = sent["view"]
    assert isinstance(view, PaginationView)
    assert sent["embed"].title == "Page 1/2"
    previous = pagination_button(view, "dizzybot:page-previous")
    next_page = pagination_button(view, "dizzybot:page-next")
    assert previous.disabled is True
    assert next_page.disabled is False

    page_interaction = SimpleNamespace(
        user=SimpleNamespace(id=42),
        response=Response(False),
        followup=Sender(),
    )
    await next_page.callback(page_interaction)
    assert view.page == 2
    assert page_interaction.response.messages[0]["embed"].title == "Page 2/2"
    assert previous.disabled is False
    assert next_page.disabled is True

    outsider = SimpleNamespace(
        user=SimpleNamespace(id=7),
        response=Response(False),
        followup=Sender(),
    )
    assert await view.interaction_check(outsider) is False
    assert outsider.response.messages[0]["ephemeral"] is True


async def test_presenter_handles_expired_interaction_without_secondary_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="dizzybot.defaults.presenter")
    presenter = DefaultPresenter()
    interaction = SimpleNamespace(response=ExpiredResponse(False), followup=Sender())

    await presenter.respond(interaction, "Too late", "Body")

    assert "interaction expired" in caplog.records[-1].getMessage()
