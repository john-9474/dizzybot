from __future__ import annotations

import math
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from dizzybot.contracts import (
    BasePermissionPolicy,
    BasePlayerManager,
    BasePresenter,
    BaseRadioCommands,
    BaseRadioRepository,
    BaseRadioResolver,
    BaseSettingsRepository,
)
from dizzybot.defaults.commands import ErrorHandlingCog
from dizzybot.domain import RadioStation
from dizzybot.errors import InvalidRequestError


class DefaultRadioCommands(
    ErrorHandlingCog,
    commands.GroupCog,
    BaseRadioCommands,
    group_name="radio",
    group_description="Save and play internet radio stations",
):
    PAGE_SIZE = 10

    def __init__(
        self,
        resolver: BaseRadioResolver,
        repository: BaseRadioRepository,
        players: BasePlayerManager,
        settings: BaseSettingsRepository,
        permissions: BasePermissionPolicy,
        presenter: BasePresenter,
        *,
        station_limit: int,
    ) -> None:
        self._resolver = resolver
        self._repository = repository
        self._players = players
        self._settings = settings
        self._permissions = permissions
        self.presenter = presenter
        self._station_limit = station_limit

    async def register(self, bot: Any) -> None:
        await bot.add_cog(self)

    @staticmethod
    def _guild_id(interaction: discord.Interaction[Any]) -> int:
        if interaction.guild_id is None:
            raise InvalidRequestError("Radio commands can only be used in a server.")
        return interaction.guild_id

    @staticmethod
    def _channel_id(interaction: discord.Interaction[Any]) -> int:
        if interaction.channel_id is None:
            raise InvalidRequestError("Run that command from a server text channel.")
        return interaction.channel_id

    async def _ensure_station_manager(self, interaction: discord.Interaction[Any]) -> int:
        guild_id = self._guild_id(interaction)
        settings = await self._settings.get(guild_id)
        self._permissions.ensure_dj(interaction, settings)
        return guild_id

    async def _autocomplete(
        self, interaction: discord.Interaction[Any], current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild_id is None:
            return []
        search = current.casefold()
        stations = await self._repository.list(interaction.guild_id)
        return [
            app_commands.Choice(name=station.name, value=station.name)
            for station in stations
            if search in station.name.casefold()
        ][:25]

    @app_commands.command(name="add", description="Save a direct radio stream (DJ/admin only)")
    @app_commands.describe(
        name="Name used to select the station", url="Direct HTTP audio stream URL"
    )
    async def add(self, interaction: discord.Interaction[Any], name: str, url: str) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild_id = await self._ensure_station_manager(interaction)
        if len(await self._repository.list(guild_id)) >= self._station_limit:
            raise InvalidRequestError(
                f"This server already has the limit of {self._station_limit} radio stations."
            )
        validated_url = await self._resolver.validate_url(url)
        station = await self._repository.add(
            RadioStation(guild_id=guild_id, name=name, url=validated_url)
        )
        safe_name = discord.utils.escape_markdown(station.name)
        await self.presenter.respond(
            interaction,
            "Radio saved",
            f"Saved **{safe_name}**. Use `/radio play` to listen.",
            ephemeral=True,
        )

    @app_commands.command(name="play", description="Play or queue a saved radio station")
    @app_commands.describe(name="Saved station name")
    async def play(self, interaction: discord.Interaction[Any], name: str) -> None:
        await interaction.response.defer(thinking=True)
        guild_id = self._guild_id(interaction)
        station = await self._repository.get(guild_id, name)
        if station is None:
            raise InvalidRequestError(f'No saved radio station is named "{name}".')
        settings = await self._settings.get(guild_id)
        player = await self._players.get_or_create(guild_id)
        channel = self._permissions.voice_channel_for(
            interaction,
            bot_channel_id=player.channel_id(),
            settings=settings,
        )
        result = await self._resolver.resolve(station, interaction.user.id)
        if not player.is_connected():
            await player.connect(channel, self._channel_id(interaction))
        await player.enqueue(result, self._channel_id(interaction))
        await self.presenter.respond(
            interaction,
            "Radio queued",
            f"Added {self.presenter.track_description(result.tracks[0])}.",
        )

    @play.autocomplete("name")
    async def play_name_autocomplete(
        self, interaction: discord.Interaction[Any], current: str
    ) -> list[app_commands.Choice[str]]:
        return await self._autocomplete(interaction, current)

    @app_commands.command(name="list", description="List this server's saved radio stations")
    async def list_stations(self, interaction: discord.Interaction[Any], page: int = 1) -> None:
        stations = await self._repository.list(self._guild_id(interaction))
        pages = max(1, math.ceil(len(stations) / self.PAGE_SIZE))
        if page < 1 or page > pages:
            raise InvalidRequestError(f"Page must be between 1 and {pages}.")
        start = (page - 1) * self.PAGE_SIZE
        selected = stations[start : start + self.PAGE_SIZE]
        if selected:
            lines = [
                f"`{start + index + 1}.` **{discord.utils.escape_markdown(station.name)}** — "
                f"<{station.url}>"
                for index, station in enumerate(selected)
            ]
        else:
            lines = ["No radio stations are saved. A DJ or administrator can use `/radio add`."]
        await self.presenter.respond(
            interaction,
            f"Radio stations — page {page}/{pages}",
            "\n".join(lines),
        )

    @app_commands.command(name="remove", description="Remove a saved station (DJ/admin only)")
    @app_commands.describe(name="Saved station name")
    async def remove(self, interaction: discord.Interaction[Any], name: str) -> None:
        guild_id = await self._ensure_station_manager(interaction)
        station = await self._repository.remove(guild_id, name)
        if station is None:
            raise InvalidRequestError(f'No saved radio station is named "{name}".')
        await self.presenter.respond(
            interaction,
            "Radio removed",
            f"Removed **{discord.utils.escape_markdown(station.name)}**.",
            ephemeral=True,
        )

    @remove.autocomplete("name")
    async def remove_name_autocomplete(
        self, interaction: discord.Interaction[Any], current: str
    ) -> list[app_commands.Choice[str]]:
        return await self._autocomplete(interaction, current)
