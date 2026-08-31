from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

import discord

from dizzybot.contracts import BasePresenter
from dizzybot.domain import QueueSnapshot, Track
from dizzybot.errors import InvalidRequestError

LOGGER = logging.getLogger(__name__)
Page = tuple[str, str]
EmbedFactory = Callable[[str, str], discord.Embed]


def format_duration(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "unknown"
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class PaginationView(discord.ui.View):
    def __init__(
        self,
        pages: tuple[Page, ...],
        *,
        owner_id: int,
        embed_factory: EmbedFactory,
    ) -> None:
        if not pages:
            raise ValueError("A paginator requires at least one page")
        super().__init__(timeout=180)
        self._pages = pages
        self._owner_id = owner_id
        self._embed_factory = embed_factory
        self._page = 0
        self.message: Any | None = None
        self._sync_buttons()

    @property
    def page(self) -> int:
        return self._page + 1

    def current_embed(self) -> discord.Embed:
        title, description = self._pages[self._page]
        return self._embed_factory(title, description)

    def _sync_buttons(self) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.custom_id == "dizzybot:page-previous":
                item.disabled = self._page == 0
            elif item.custom_id == "dizzybot:page-next":
                item.disabled = self._page == len(self._pages) - 1

    async def interaction_check(self, interaction: discord.Interaction[Any]) -> bool:
        if interaction.user.id == self._owner_id:
            return True
        embed = self._embed_factory(
            "Paginator unavailable",
            "Only the person who opened this list can change its page.",
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        custom_id="dizzybot:page-previous",
    )
    async def previous(
        self, interaction: discord.Interaction[Any], _button: discord.ui.Button[Any]
    ) -> None:
        self._page = max(0, self._page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        custom_id="dizzybot:page-next",
    )
    async def next_page(
        self, interaction: discord.Interaction[Any], _button: discord.ui.Button[Any]
    ) -> None:
        self._page = min(len(self._pages) - 1, self._page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            LOGGER.debug("Could not disable an expired paginator")


class DefaultPresenter(BasePresenter):
    PAGE_SIZE = 10

    def __init__(self) -> None:
        self._client: Any | None = None

    def attach(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _embed(title: str, description: str, *, error: bool) -> discord.Embed:
        colour = discord.Colour.red() if error else discord.Colour.blurple()
        return discord.Embed(title=title, description=description, colour=colour)

    async def respond(
        self,
        interaction: Any,
        title: str,
        description: str,
        *,
        error: bool = False,
        ephemeral: bool = False,
    ) -> None:
        embed = self._embed(title, description, error=error)
        await self._send_interaction_embed(interaction, embed, ephemeral=ephemeral)

    async def respond_paginated(
        self,
        interaction: Any,
        pages: tuple[Page, ...],
        *,
        ephemeral: bool = False,
    ) -> None:
        view = PaginationView(
            pages,
            owner_id=interaction.user.id,
            embed_factory=lambda title, description: self._embed(title, description, error=False),
        )
        view.message = await self._send_interaction_embed(
            interaction,
            view.current_embed(),
            ephemeral=ephemeral,
            view=view,
        )

    @staticmethod
    async def _send_interaction_embed(
        interaction: Any,
        embed: discord.Embed,
        *,
        ephemeral: bool = False,
        view: discord.ui.View | None = None,
    ) -> Any | None:
        try:
            if interaction.response.is_done():
                options: dict[str, Any] = {
                    "embed": embed,
                    "ephemeral": ephemeral,
                    "view": view,
                }
                if view is not None:
                    options["wait"] = True
                return await interaction.followup.send(**options)
            await interaction.response.send_message(
                embed=embed,
                ephemeral=ephemeral,
                view=view,
            )
            if view is not None and hasattr(interaction, "original_response"):
                return await interaction.original_response()
        except discord.NotFound as send_error:
            if send_error.code != 10062:
                raise
            LOGGER.warning("Discord interaction expired before a response could be sent")
        return None

    def now_playing_embed(self, snapshot: QueueSnapshot) -> discord.Embed:
        track = snapshot.current
        if track is None:
            raise InvalidRequestError("Nothing is currently playing.")

        safe_title = discord.utils.escape_markdown(track.title)
        safe_author = discord.utils.escape_markdown(track.author)
        state = "Paused" if snapshot.paused else "Now playing"
        embed = self._embed(
            state,
            f"[{safe_title}]({track.uri})\nby **{safe_author}**",
            error=False,
        )
        if track.artwork_url:
            embed.set_thumbnail(url=track.artwork_url)

        if track.is_stream:
            playback = "Live stream"
        else:
            playback = (
                f"{format_duration(snapshot.position_ms)} / {format_duration(track.duration_ms)}"
            )
        embed.add_field(name="Playback", value=playback, inline=True)

        if snapshot.queue_position is not None and snapshot.queue_total:
            queue_position = f"{snapshot.queue_position} of {snapshot.queue_total}"
        else:
            queue_position = "Not available"
        embed.add_field(name="Queue position", value=queue_position, inline=True)

        if track.playlist_name:
            safe_playlist = discord.utils.escape_markdown(track.playlist_name)
            playlist = f"**{safe_playlist}**"
            if track.playlist_position is not None and track.playlist_size is not None:
                playlist += f" — track {track.playlist_position} of {track.playlist_size}"
            embed.add_field(name="Playlist", value=playlist, inline=False)

        requester = f"<@{track.requested_by}>" if track.requested_by is not None else "Unknown"
        embed.add_field(name="Requested by", value=requester, inline=True)
        embed.set_footer(
            text=(
                f"Source: {track.source.value} • Volume: {snapshot.volume}% • "
                f"Repeat: {snapshot.repeat_mode.value}"
            )
        )
        return embed

    async def respond_now_playing(self, interaction: Any, snapshot: QueueSnapshot) -> None:
        await self._send_interaction_embed(interaction, self.now_playing_embed(snapshot))

    async def notify(
        self,
        channel_id: int,
        title: str,
        description: str,
        *,
        error: bool = False,
    ) -> None:
        if self._client is None:
            return
        channel = self._client.get_channel(channel_id)
        if channel is not None and hasattr(channel, "send"):
            await channel.send(embed=self._embed(title, description, error=error))

    def track_description(self, track: Track) -> str:
        safe_title = discord.utils.escape_markdown(track.title)
        safe_author = discord.utils.escape_markdown(track.author)
        duration = "live" if track.is_stream else format_duration(track.duration_ms)
        return f"[{safe_title}]({track.uri}) — {safe_author} (`{duration}`)"

    def queue_page(self, snapshot: QueueSnapshot, page: int) -> tuple[str, str]:
        total = len(snapshot.upcoming)
        pages = max(1, math.ceil(total / self.PAGE_SIZE))
        if page < 1 or page > pages:
            raise InvalidRequestError(f"Page must be between 1 and {pages}.")
        start = (page - 1) * self.PAGE_SIZE
        entries = snapshot.upcoming[start : start + self.PAGE_SIZE]
        lines = [
            f"`{start + offset + 1}.` {self.track_description(track)}"
            for offset, track in enumerate(entries)
        ]
        if not lines:
            lines.append("The queue is empty.")
        if snapshot.current is not None:
            lines.insert(0, f"**Now playing:** {self.track_description(snapshot.current)}\n")
        title = f"Queue — page {page}/{pages}"
        footer = f"\nRepeat: `{snapshot.repeat_mode.value}` · Volume: `{snapshot.volume}%`"
        return title, "\n".join(lines) + footer
