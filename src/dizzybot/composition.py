"""The single intended class-selection point for source-level customization.

Forkers can add subclasses anywhere in the source tree, then replace the relevant
``Default...`` constructor below. No dynamic imports or plugin loader are involved.
"""

from __future__ import annotations

from dataclasses import dataclass

from dizzybot.config import AppConfig
from dizzybot.contracts import (
    BaseAudioBackend,
    BaseBotRuntime,
    BaseHealthService,
    BaseMusicCommands,
    BasePermissionPolicy,
    BasePlaybackControls,
    BasePlayerManager,
    BasePresenter,
    BaseRadioCommands,
    BaseRadioRepository,
    BaseRadioResolver,
    BaseSettingsCommands,
    BaseSettingsRepository,
    BaseTrackResolver,
)
from dizzybot.defaults.audio import DefaultAudioBackend
from dizzybot.defaults.commands import DefaultMusicCommands, DefaultSettingsCommands
from dizzybot.defaults.controls import DefaultPlaybackControls
from dizzybot.defaults.health import DefaultHealthService
from dizzybot.defaults.permissions import DefaultPermissionPolicy
from dizzybot.defaults.player import DefaultGuildPlayer, DefaultPlayerManager
from dizzybot.defaults.presenter import DefaultPresenter
from dizzybot.defaults.queue import DefaultQueue
from dizzybot.defaults.radio import DefaultRadioResolver
from dizzybot.defaults.radio_commands import DefaultRadioCommands
from dizzybot.defaults.radio_repository import DefaultRadioRepository
from dizzybot.defaults.resolver import DefaultTrackResolver
from dizzybot.defaults.runtime import DefaultBotRuntime, DefaultDiscordBot
from dizzybot.defaults.settings import DefaultSettingsRepository
from dizzybot.domain import Source


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    runtime: BaseBotRuntime
    audio: BaseAudioBackend
    resolver: BaseTrackResolver
    players: BasePlayerManager
    settings: BaseSettingsRepository
    radios: BaseRadioRepository
    radio_resolver: BaseRadioResolver
    permissions: BasePermissionPolicy
    presenter: BasePresenter
    controls: BasePlaybackControls
    music_commands: BaseMusicCommands
    settings_commands: BaseSettingsCommands
    radio_commands: BaseRadioCommands
    health: BaseHealthService


def build_services(config: AppConfig) -> ServiceContainer:
    bot = DefaultDiscordBot()
    audio = DefaultAudioBackend(config.lavalink)
    settings = DefaultSettingsRepository(
        config.database.url,
        default_volume=config.bot.default_volume,
        default_idle_timeout_seconds=config.bot.idle_timeout_seconds,
        default_stay_connected=config.bot.stay_connected,
        default_search_source=config.bot.default_search_source,
    )
    radios = DefaultRadioRepository(config.database.url)
    presenter = DefaultPresenter()
    permissions = DefaultPermissionPolicy()
    controls = DefaultPlaybackControls(bot, settings, permissions, presenter)
    available_sources = {
        Source.YOUTUBE,
        Source.SOUNDCLOUD,
        Source.APPLE_MUSIC,
        Source.BANDCAMP,
    }
    if config.spotify.configured:
        available_sources.add(Source.SPOTIFY)
    if config.tidal.configured:
        available_sources.add(Source.TIDAL)
    resolver = DefaultTrackResolver(audio, available_sources=available_sources)
    radio_resolver = DefaultRadioResolver(
        audio,
        allow_private_networks=config.bot.allow_private_radio_streams,
    )
    players = DefaultPlayerManager(
        audio,
        settings,
        presenter,
        controls,
        player_factory=DefaultGuildPlayer,
        queue_factory=DefaultQueue,
        queue_limit=config.bot.queue_track_limit,
    )
    music_commands = DefaultMusicCommands(
        resolver, players, settings, permissions, presenter, config.bot
    )
    settings_commands = DefaultSettingsCommands(
        settings, players, permissions, presenter, available_sources
    )
    radio_commands = DefaultRadioCommands(
        radio_resolver,
        radios,
        players,
        settings,
        permissions,
        presenter,
        station_limit=config.bot.radio_station_limit,
    )
    health = DefaultHealthService(
        config.health,
        discord_ready=bot.is_ready,
        audio_ready=audio.is_ready,
        storage_ready=lambda: settings.is_ready() and radios.is_ready(),
    )
    runtime = DefaultBotRuntime(
        bot,
        config,
        audio,
        players,
        settings,
        radios,
        presenter,
        music_commands,
        settings_commands,
        radio_commands,
        health,
    )
    return ServiceContainer(
        runtime=runtime,
        audio=audio,
        resolver=resolver,
        players=players,
        settings=settings,
        radios=radios,
        radio_resolver=radio_resolver,
        permissions=permissions,
        presenter=presenter,
        controls=controls,
        music_commands=music_commands,
        settings_commands=settings_commands,
        radio_commands=radio_commands,
        health=health,
    )
