from __future__ import annotations

import asyncio
import contextlib
import logging

import discord
from discord.ext import commands

from dizzybot.config import AppConfig
from dizzybot.contracts import (
    BaseAudioBackend,
    BaseBotRuntime,
    BaseHealthService,
    BaseMusicCommands,
    BasePlayerManager,
    BasePresenter,
    BaseRadioCommands,
    BaseRadioRepository,
    BaseSettingsCommands,
    BaseSettingsRepository,
)

LOGGER = logging.getLogger(__name__)


class DefaultDiscordBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )


class DefaultBotRuntime(BaseBotRuntime):
    def __init__(
        self,
        bot: DefaultDiscordBot,
        config: AppConfig,
        audio: BaseAudioBackend,
        players: BasePlayerManager,
        settings: BaseSettingsRepository,
        radios: BaseRadioRepository,
        presenter: BasePresenter,
        music_commands: BaseMusicCommands,
        settings_commands: BaseSettingsCommands,
        radio_commands: BaseRadioCommands,
        health: BaseHealthService,
    ) -> None:
        self.bot = bot
        self._config = config
        self._audio = audio
        self._players = players
        self._settings = settings
        self._radios = radios
        self._presenter = presenter
        self._music_commands = music_commands
        self._settings_commands = settings_commands
        self._radio_commands = radio_commands
        self._health = health
        self._audio_task: asyncio.Task[None] | None = None
        self._sync_lock = asyncio.Lock()
        self._commands_synced = False
        self._closing = False
        bot.add_listener(self._on_ready, "on_ready")

    async def _connect_audio(self) -> None:
        while not self._closing and not self._audio.is_ready():
            try:
                await self._audio.start(self.bot)
            except Exception:
                LOGGER.exception("Could not connect to Lavalink; retrying")
                await asyncio.sleep(self._config.lavalink.retry_delay_seconds)
            else:
                LOGGER.info("Connected to Lavalink")

    async def _sync_commands(self) -> None:
        async with self._sync_lock:
            if self._commands_synced:
                return
            guild_id = self._config.bot.command_sync_guild_id
            if guild_id is None:
                synced = await self.bot.tree.sync()
                LOGGER.info("Synced %d global application commands", len(synced))
            else:
                guild = discord.Object(id=guild_id)
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                LOGGER.info("Synced %d application commands to guild %d", len(synced), guild_id)
            self._commands_synced = True

    async def _on_ready(self) -> None:
        LOGGER.info("Logged in to Discord as %s", self.bot.user)
        if self._audio_task is None or self._audio_task.done():
            self._audio_task = asyncio.create_task(
                self._connect_audio(), name="dizzybot-lavalink-connect"
            )
        try:
            await self._sync_commands()
        except Exception:
            LOGGER.exception("Could not synchronize application commands")

    async def start(self) -> None:
        await self._settings.start()
        await self._radios.start()
        self._presenter.attach(self.bot)
        await self._music_commands.register(self.bot)
        await self._settings_commands.register(self.bot)
        await self._radio_commands.register(self.bot)
        await self._health.start()
        try:
            await self.bot.start(self._config.bot.discord_token.get_secret_value(), reconnect=True)
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._audio_task is not None:
            self._audio_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._audio_task
        await self._players.close()
        await self._audio.close()
        await self._health.close()
        await self._radios.close()
        await self._settings.close()
        if not self.bot.is_closed():
            await self.bot.close()
