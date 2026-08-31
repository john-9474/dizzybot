from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import replace
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from dizzybot.config import BotConfig
from dizzybot.contracts import (
    BaseMusicCommands,
    BasePermissionPolicy,
    BasePlayerManager,
    BasePresenter,
    BaseSettingsCommands,
    BaseSettingsRepository,
    BaseTrackResolver,
)
from dizzybot.domain import RepeatMode, ResolveRequest, Source
from dizzybot.errors import DizzyBotError, InvalidRequestError, PlayerStateError

LOGGER = logging.getLogger(__name__)


def parse_seek_position(value: str) -> int:
    text = value.strip()
    if not text:
        raise InvalidRequestError("A seek position is required.")
    try:
        if ":" not in text:
            seconds = int(text)
        else:
            parts = [int(part) for part in text.split(":")]
            if len(parts) not in {2, 3} or any(part < 0 for part in parts):
                raise ValueError
            if any(part >= 60 for part in parts[1:]):
                raise ValueError
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + part
    except ValueError as error:
        raise InvalidRequestError("Use seconds, MM:SS, or HH:MM:SS.") from error
    if seconds < 0:
        raise InvalidRequestError("Seek position cannot be negative.")
    return seconds * 1000


class ErrorHandlingCog:
    presenter: BasePresenter

    async def cog_app_command_error(
        self, interaction: discord.Interaction[Any], error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, DizzyBotError):
            await self.presenter.respond(
                interaction,
                "Cannot complete command",
                str(original),
                error=True,
                ephemeral=True,
            )
            return
        LOGGER.exception("Unhandled application command error", exc_info=original)
        await self.presenter.respond(
            interaction,
            "Unexpected error",
            "Something went wrong. Check the bot logs for details.",
            error=True,
            ephemeral=True,
        )


class DefaultMusicCommands(ErrorHandlingCog, commands.Cog, BaseMusicCommands):
    def __init__(
        self,
        resolver: BaseTrackResolver,
        players: BasePlayerManager,
        settings: BaseSettingsRepository,
        permissions: BasePermissionPolicy,
        presenter: BasePresenter,
        config: BotConfig,
    ) -> None:
        self._resolver = resolver
        self._players = players
        self._settings = settings
        self._permissions = permissions
        self.presenter = presenter
        self._config = config

    async def register(self, bot: Any) -> None:
        await bot.add_cog(self)

    @staticmethod
    def _guild_id(interaction: discord.Interaction[Any]) -> int:
        if interaction.guild_id is None:
            raise InvalidRequestError("Music commands can only be used in a server.")
        return interaction.guild_id

    @staticmethod
    def _channel_id(interaction: discord.Interaction[Any]) -> int:
        if interaction.channel_id is None:
            raise InvalidRequestError("Run that command from a server text channel.")
        return interaction.channel_id

    async def _controlled_player(self, interaction: discord.Interaction[Any]) -> Any:
        guild_id = self._guild_id(interaction)
        player = await self._players.get_or_create(guild_id)
        settings = await self._settings.get(guild_id)
        self._permissions.voice_channel_for(
            interaction,
            bot_channel_id=player.channel_id(),
            settings=settings,
        )
        return player

    @app_commands.command(name="play", description="Play a track or add it to the queue")
    @app_commands.describe(
        query="Search text or a supported URL", source="Source used for text searches"
    )
    @app_commands.choices(
        source=[
            app_commands.Choice(name="Automatic", value="auto"),
            app_commands.Choice(name="YouTube", value="youtube"),
            app_commands.Choice(name="SoundCloud", value="soundcloud"),
            app_commands.Choice(name="Spotify", value="spotify"),
            app_commands.Choice(name="Apple Music", value="apple_music"),
            app_commands.Choice(name="TIDAL", value="tidal"),
            app_commands.Choice(name="Bandcamp", value="bandcamp"),
        ]
    )
    async def play(
        self,
        interaction: discord.Interaction[Any],
        query: str,
        source: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        guild_id = self._guild_id(interaction)
        settings = await self._settings.get(guild_id)
        player = await self._players.get_or_create(guild_id)
        channel = self._permissions.voice_channel_for(
            interaction,
            bot_channel_id=player.channel_id(),
            settings=settings,
        )
        if not player.is_connected():
            await player.connect(channel, self._channel_id(interaction))
        chosen_source = Source(source.value) if source else Source.AUTO
        result = await self._resolver.resolve(
            ResolveRequest(
                query=query,
                source=chosen_source,
                requester_id=interaction.user.id,
                max_items=self._config.playlist_track_limit,
                default_source=settings.default_search_source,
            )
        )
        added = await player.enqueue(result, self._channel_id(interaction))
        if result.is_playlist:
            playlist_name = result.playlist.name if result.playlist else "playlist"
            detail = f"Added **{added}** tracks from **{playlist_name}**."
        else:
            detail = f"Added {self.presenter.track_description(result.tracks[0])}."
        if result.skipped_count:
            detail += f" Skipped **{result.skipped_count}** unavailable, live, or excess tracks."
        await self.presenter.respond(interaction, "Queued", detail)

    @app_commands.command(name="join", description="Join your voice channel")
    async def join(self, interaction: discord.Interaction[Any]) -> None:
        guild_id = self._guild_id(interaction)
        settings = await self._settings.get(guild_id)
        player = await self._players.get_or_create(guild_id)
        channel = self._permissions.voice_channel_for(
            interaction, bot_channel_id=player.channel_id(), settings=settings
        )
        if player.is_connected():
            await self.presenter.respond(interaction, "Voice", "Already connected to voice.")
            return
        await player.connect(channel, self._channel_id(interaction))
        await self.presenter.respond(interaction, "Voice", f"Joined **{channel.name}**.")

    @app_commands.command(
        name="leave", description="Stop playback, clear the queue, and leave voice"
    )
    async def leave(self, interaction: discord.Interaction[Any]) -> None:
        player = await self._controlled_player(interaction)
        if not player.is_connected():
            raise PlayerStateError()
        await player.leave()
        await self.presenter.respond(
            interaction, "Disconnected", "Stopped playback and left voice."
        )

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction[Any]) -> None:
        player = await self._controlled_player(interaction)
        await player.pause()
        await self.presenter.respond(interaction, "Paused", "Playback is paused.")

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction[Any]) -> None:
        player = await self._controlled_player(interaction)
        await player.resume()
        await self.presenter.respond(interaction, "Resumed", "Playback has resumed.")

    @app_commands.command(name="skip", description="Skip the current track")
    async def skip(self, interaction: discord.Interaction[Any]) -> None:
        player = await self._controlled_player(interaction)
        track = await player.skip()
        await self.presenter.respond(
            interaction, "Skipped", self.presenter.track_description(track)
        )

    @app_commands.command(name="stop", description="Stop playback and clear upcoming tracks")
    async def stop(self, interaction: discord.Interaction[Any]) -> None:
        player = await self._controlled_player(interaction)
        await player.stop()
        await self.presenter.respond(interaction, "Stopped", "Playback and the queue were stopped.")

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue(self, interaction: discord.Interaction[Any], page: int = 1) -> None:
        guild_id = self._guild_id(interaction)
        player = self._players.get(guild_id)
        if player is None:
            raise PlayerStateError("The queue is empty.")
        title, description = self.presenter.queue_page(await player.snapshot(), page)
        await self.presenter.respond(interaction, title, description)

    @app_commands.command(name="nowplaying", description="Show the current track")
    async def nowplaying(self, interaction: discord.Interaction[Any]) -> None:
        guild_id = self._guild_id(interaction)
        player = self._players.get(guild_id)
        if player is None:
            raise PlayerStateError("Nothing is currently playing.")
        snapshot = await player.snapshot()
        if snapshot.current is None:
            raise PlayerStateError("Nothing is currently playing.")
        await self.presenter.respond_now_playing(interaction, snapshot)

    @app_commands.command(name="remove", description="Remove an upcoming track by queue position")
    async def remove(self, interaction: discord.Interaction[Any], position: int) -> None:
        player = await self._controlled_player(interaction)
        track = await player.remove(position)
        await self.presenter.respond(
            interaction, "Removed", self.presenter.track_description(track)
        )

    @app_commands.command(
        name="move", description="Move an upcoming track to another queue position"
    )
    async def move(
        self, interaction: discord.Interaction[Any], from_position: int, to_position: int
    ) -> None:
        player = await self._controlled_player(interaction)
        track = await player.move(from_position, to_position)
        await self.presenter.respond(
            interaction,
            "Moved",
            f"Moved **{track.title}** to position **{to_position}**.",
        )

    @app_commands.command(
        name="clear", description="Clear upcoming tracks without stopping playback"
    )
    async def clear(self, interaction: discord.Interaction[Any]) -> None:
        player = await self._controlled_player(interaction)
        count = await player.clear()
        await self.presenter.respond(interaction, "Queue cleared", f"Removed **{count}** tracks.")

    @app_commands.command(name="shuffle", description="Shuffle upcoming tracks")
    async def shuffle(self, interaction: discord.Interaction[Any]) -> None:
        player = await self._controlled_player(interaction)
        await player.shuffle()
        await self.presenter.respond(interaction, "Shuffled", "The upcoming queue was shuffled.")

    @app_commands.command(name="repeat", description="Set the repeat mode")
    @app_commands.choices(
        mode=[app_commands.Choice(name=mode.value.title(), value=mode.value) for mode in RepeatMode]
    )
    async def repeat(
        self, interaction: discord.Interaction[Any], mode: app_commands.Choice[str]
    ) -> None:
        player = await self._controlled_player(interaction)
        selected = RepeatMode(mode.value)
        await player.set_repeat(selected)
        await self.presenter.respond(interaction, "Repeat", f"Repeat is now **{selected.value}**.")

    @app_commands.command(name="volume", description="Set session volume from 0 to 100")
    async def volume(self, interaction: discord.Interaction[Any], percent: int) -> None:
        player = await self._controlled_player(interaction)
        await player.set_volume(percent)
        await self.presenter.respond(interaction, "Volume", f"Volume set to **{percent}%**.")

    @app_commands.command(name="seek", description="Seek using seconds, MM:SS, or HH:MM:SS")
    async def seek(self, interaction: discord.Interaction[Any], position: str) -> None:
        player = await self._controlled_player(interaction)
        milliseconds = parse_seek_position(position)
        await player.seek(milliseconds)
        await self.presenter.respond(
            interaction, "Seeked", f"Moved to **{milliseconds // 1000} seconds**."
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        del before, after
        player = self._players.get(member.guild.id)
        if player is None or player.channel_id() is None:
            return
        channel_id = player.channel_id()
        if channel_id is None:
            return
        channel = member.guild.get_channel(channel_id)
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await player.update_human_presence(any(not item.bot for item in channel.members))


class DefaultSettingsCommands(
    ErrorHandlingCog,
    commands.GroupCog,
    BaseSettingsCommands,
    group_name="settings",
    group_description="View or change server music settings",
):
    def __init__(
        self,
        settings: BaseSettingsRepository,
        players: BasePlayerManager,
        permissions: BasePermissionPolicy,
        presenter: BasePresenter,
        available_sources: Collection[Source],
    ) -> None:
        self._settings = settings
        self._players = players
        self._permissions = permissions
        self.presenter = presenter
        self._available_sources = frozenset(available_sources)

    async def register(self, bot: Any) -> None:
        await bot.add_cog(self)

    def _guild_id(self, interaction: discord.Interaction[Any]) -> int:
        self._permissions.ensure_manage_guild(interaction)
        return self._server_id(interaction)

    @staticmethod
    def _server_id(interaction: discord.Interaction[Any]) -> int:
        if interaction.guild_id is None:
            raise InvalidRequestError("Settings can only be changed in a server.")
        return interaction.guild_id

    async def _save(self, settings: Any) -> None:
        saved = await self._settings.save(settings)
        player = self._players.get(saved.guild_id)
        if player is not None:
            await player.update_settings(saved)

    @app_commands.command(name="show", description="Show this server's music settings")
    async def show(self, interaction: discord.Interaction[Any]) -> None:
        settings = await self._settings.get(self._guild_id(interaction))
        dj_role = f"<@&{settings.dj_role_id}>" if settings.dj_role_id else "Not configured"
        description = (
            f"Default volume: **{settings.default_volume}%**\n"
            f"Empty/idle timeout: **{settings.idle_timeout_seconds}s**\n"
            f"24/7 mode: **{'Enabled' if settings.stay_connected else 'Disabled'}**\n"
            f"DJ role: **{dj_role}**\n"
            f"Search provider: **{settings.default_search_source.value}**"
        )
        await self.presenter.respond(interaction, "Server settings", description, ephemeral=True)

    @app_commands.command(name="volume", description="Set the default session volume")
    async def volume(self, interaction: discord.Interaction[Any], percent: int) -> None:
        if not 0 <= percent <= 100:
            raise InvalidRequestError("Volume must be between 0 and 100.")
        settings = await self._settings.get(self._guild_id(interaction))
        await self._save(replace(settings, default_volume=percent))
        await self.presenter.respond(
            interaction, "Settings saved", f"Default volume is **{percent}%**.", ephemeral=True
        )

    @app_commands.command(
        name="idle-timeout", description="Set empty or idle voice disconnect time in seconds"
    )
    async def idle_timeout(self, interaction: discord.Interaction[Any], seconds: int) -> None:
        if not 30 <= seconds <= 86400:
            raise InvalidRequestError("Idle timeout must be between 30 and 86400 seconds.")
        settings = await self._settings.get(self._guild_id(interaction))
        await self._save(replace(settings, idle_timeout_seconds=seconds))
        await self.presenter.respond(
            interaction,
            "Settings saved",
            f"Empty/idle timeout is **{seconds}s**.",
            ephemeral=True,
        )

    @app_commands.command(name="24-7", description="Stay connected when nobody is listening")
    async def twenty_four_seven(self, interaction: discord.Interaction[Any], enabled: bool) -> None:
        guild_id = self._server_id(interaction)
        settings = await self._settings.get(guild_id)
        self._permissions.ensure_dj(interaction, settings)
        await self._save(replace(settings, stay_connected=enabled))
        state = "enabled" if enabled else "disabled"
        await self.presenter.respond(
            interaction,
            "24/7 mode",
            f"24/7 mode is now **{state}**.",
            ephemeral=True,
        )

    @app_commands.command(name="dj-role", description="Set the role allowed to control remotely")
    async def dj_role(self, interaction: discord.Interaction[Any], role: discord.Role) -> None:
        settings = await self._settings.get(self._guild_id(interaction))
        await self._save(replace(settings, dj_role_id=role.id))
        await self.presenter.respond(
            interaction, "Settings saved", f"DJ role set to {role.mention}.", ephemeral=True
        )

    @app_commands.command(name="search-provider", description="Set the default text-search source")
    @app_commands.choices(
        source=[
            app_commands.Choice(name="YouTube", value="youtube"),
            app_commands.Choice(name="SoundCloud", value="soundcloud"),
            app_commands.Choice(name="Spotify", value="spotify"),
            app_commands.Choice(name="Apple Music", value="apple_music"),
            app_commands.Choice(name="TIDAL", value="tidal"),
            app_commands.Choice(name="Bandcamp", value="bandcamp"),
        ]
    )
    async def search_provider(
        self, interaction: discord.Interaction[Any], source: app_commands.Choice[str]
    ) -> None:
        selected = Source(source.value)
        if selected not in self._available_sources:
            setup = {
                Source.SPOTIFY: "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET",
                Source.TIDAL: "TIDAL_TOKEN",
            }.get(selected)
            detail = f" Provide {setup} first." if setup else ""
            raise InvalidRequestError(
                f"{selected.value.replace('_', ' ').title()} is not configured.{detail}"
            )
        settings = await self._settings.get(self._guild_id(interaction))
        await self._save(replace(settings, default_search_source=selected))
        await self.presenter.respond(
            interaction,
            "Settings saved",
            f"Default search provider is **{selected.value}**.",
            ephemeral=True,
        )

    @app_commands.command(name="reset", description="Reset all server music settings")
    async def reset(self, interaction: discord.Interaction[Any]) -> None:
        guild_id = self._guild_id(interaction)
        settings = await self._settings.reset(guild_id)
        player = self._players.get(guild_id)
        if player is not None:
            await player.update_settings(settings)
        await self.presenter.respond(
            interaction,
            "Settings reset",
            "All server settings use deployment defaults.",
            ephemeral=True,
        )
