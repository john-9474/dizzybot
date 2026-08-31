from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import discord

from dizzybot.contracts import (
    BaseGuildPlayer,
    BasePermissionPolicy,
    BasePlaybackControls,
    BasePresenter,
    BaseSettingsRepository,
)
from dizzybot.domain import QueueSnapshot
from dizzybot.errors import DizzyBotError

LOGGER = logging.getLogger(__name__)
ControlAction = Literal["previous", "play_pause", "skip", "stop"]


class PlaybackControlView(discord.ui.View):
    def __init__(self, guild_id: int, controller: DefaultPlaybackControls) -> None:
        super().__init__(timeout=None)
        self._guild_id = guild_id
        self._controller = controller

    def sync(self, snapshot: QueueSnapshot) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            item.disabled = snapshot.current is None
            if item.custom_id == "dizzybot:previous":
                item.disabled = not snapshot.can_go_previous
            elif item.custom_id == "dizzybot:play-pause":
                item.label = "Play" if snapshot.paused else "Pause"
                item.emoji = "▶️" if snapshot.paused else "⏸️"
                item.style = (
                    discord.ButtonStyle.success if snapshot.paused else discord.ButtonStyle.primary
                )

    def disable_all(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    @discord.ui.button(
        label="Previous",
        emoji="⏮️",
        style=discord.ButtonStyle.secondary,
        custom_id="dizzybot:previous",
    )
    async def previous(
        self, interaction: discord.Interaction[Any], _button: discord.ui.Button[Any]
    ) -> None:
        await self._controller.handle(self._guild_id, interaction, "previous")

    @discord.ui.button(
        label="Pause",
        emoji="⏸️",
        style=discord.ButtonStyle.primary,
        custom_id="dizzybot:play-pause",
    )
    async def play_pause(
        self, interaction: discord.Interaction[Any], _button: discord.ui.Button[Any]
    ) -> None:
        await self._controller.handle(self._guild_id, interaction, "play_pause")

    @discord.ui.button(
        label="Skip",
        emoji="⏭️",
        style=discord.ButtonStyle.secondary,
        custom_id="dizzybot:skip",
    )
    async def skip(
        self, interaction: discord.Interaction[Any], _button: discord.ui.Button[Any]
    ) -> None:
        await self._controller.handle(self._guild_id, interaction, "skip")

    @discord.ui.button(
        label="Stop",
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        custom_id="dizzybot:stop",
    )
    async def stop_playback(
        self, interaction: discord.Interaction[Any], _button: discord.ui.Button[Any]
    ) -> None:
        await self._controller.handle(self._guild_id, interaction, "stop")

    async def on_error(
        self,
        interaction: discord.Interaction[Any],
        error: Exception,
        item: discord.ui.Item[Any],
    ) -> None:
        del item
        await self._controller.handle_error(interaction, error)


@dataclass(slots=True)
class _Panel:
    channel_id: int
    message: Any
    view: PlaybackControlView


class DefaultPlaybackControls(BasePlaybackControls):
    def __init__(
        self,
        client: Any,
        settings: BaseSettingsRepository,
        permissions: BasePermissionPolicy,
        presenter: BasePresenter,
        *,
        repost_player_controls: bool = True,
    ) -> None:
        self._client = client
        self._settings = settings
        self._permissions = permissions
        self._presenter = presenter
        self._repost_player_controls = repost_player_controls
        self._players: dict[int, BaseGuildPlayer] = {}
        self._panels: dict[int, _Panel] = {}

    def bind_player(self, player: BaseGuildPlayer) -> None:
        self._players[player.guild_id] = player

    async def update(
        self,
        guild_id: int,
        channel_id: int,
        snapshot: QueueSnapshot,
    ) -> None:
        if snapshot.current is None:
            await self.clear(guild_id)
            return
        embed = self._presenter.now_playing_embed(snapshot)
        panel = self._panels.get(guild_id)
        if panel is not None and panel.channel_id == channel_id:
            panel.view.sync(snapshot)
            try:
                await panel.message.edit(embed=embed, view=panel.view)
                return
            except discord.NotFound:
                panel.view.stop()
                self._panels.pop(guild_id, None)
            except discord.HTTPException:
                LOGGER.warning("Could not update playback controls for guild %d", guild_id)
                return
        elif panel is not None:
            await self.clear(guild_id)

        channel = self._client.get_channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            return
        view = PlaybackControlView(guild_id, self)
        view.sync(snapshot)
        try:
            message = await channel.send(embed=embed, view=view)
        except discord.HTTPException:
            LOGGER.warning("Could not send playback controls for guild %d", guild_id)
            view.stop()
            return
        self._panels[guild_id] = _Panel(channel_id, message, view)

    async def repost(
        self,
        guild_id: int,
        channel_id: int,
        snapshot: QueueSnapshot,
    ) -> None:
        if not self._repost_player_controls or snapshot.current is None:
            return
        panel = self._panels.pop(guild_id, None)
        if panel is not None:
            panel.view.disable_all()
            panel.view.stop()
            try:
                await panel.message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                try:
                    await panel.message.edit(view=panel.view)
                except discord.HTTPException:
                    LOGGER.debug("Could not retire old playback controls for guild %d", guild_id)
        await self.update(guild_id, channel_id, snapshot)

    async def clear(self, guild_id: int) -> None:
        panel = self._panels.pop(guild_id, None)
        if panel is None:
            return
        panel.view.disable_all()
        panel.view.stop()
        try:
            await panel.message.edit(view=panel.view)
        except discord.HTTPException:
            LOGGER.debug("Could not disable playback controls for guild %d", guild_id)

    async def handle(
        self,
        guild_id: int,
        interaction: discord.Interaction[Any],
        action: ControlAction,
    ) -> None:
        player = self._players.get(guild_id)
        if interaction.guild_id != guild_id or player is None:
            await self._presenter.respond(
                interaction,
                "Controls unavailable",
                "That playback session is no longer active.",
                error=True,
                ephemeral=True,
            )
            return
        try:
            settings = await self._settings.get(guild_id)
            self._permissions.voice_channel_for(
                interaction,
                bot_channel_id=player.channel_id(),
                settings=settings,
            )
            if not interaction.response.is_done():
                await interaction.response.defer()
            if action == "previous":
                await player.previous()
            elif action == "play_pause":
                snapshot = await player.snapshot()
                if snapshot.paused:
                    await player.resume()
                else:
                    await player.pause()
            elif action == "skip":
                await player.skip()
            elif action == "stop":
                await player.stop()
        except DizzyBotError as error:
            await self._presenter.respond(
                interaction,
                "Cannot control playback",
                str(error),
                error=True,
                ephemeral=True,
            )

    async def handle_error(self, interaction: discord.Interaction[Any], error: Exception) -> None:
        if isinstance(error, DizzyBotError):
            message = str(error)
        else:
            LOGGER.exception("Unhandled playback control error", exc_info=error)
            message = "Something went wrong. Check the bot logs for details."
        await self._presenter.respond(
            interaction,
            "Cannot control playback",
            message,
            error=True,
            ephemeral=True,
        )
