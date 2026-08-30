from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from dizzybot.config import AppConfig
from dizzybot.defaults.runtime import DefaultBotRuntime, DefaultDiscordBot
from tests.fakes import FakeAudioBackend, FakePresenter, FakeSettingsRepository


class FakeBot:
    def __init__(self) -> None:
        self.listeners: dict[str, Any] = {}
        self.closed = False
        self.user = "Dizzy"
        self.tree = SimpleNamespace(sync=self.sync, copy_global_to=lambda **kwargs: None)
        self.synced: list[Any] = []

    def add_listener(self, callback: Any, name: str) -> None:
        self.listeners[name] = callback

    async def add_cog(self, cog: Any) -> None:
        del cog

    async def sync(self, **kwargs: Any) -> list[int]:
        self.synced.append(kwargs)
        return [1]

    async def start(self, token: str, *, reconnect: bool) -> None:
        assert token == "token"
        assert reconnect is True
        await self.listeners["on_ready"]()
        await asyncio.sleep(0)

    async def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed

    def is_ready(self) -> bool:
        return not self.closed


class Lifecycle:
    def __init__(self) -> None:
        self.started = 0
        self.closed = 0

    async def register(self, bot: Any) -> None:
        del bot
        self.started += 1

    async def start(self) -> None:
        self.started += 1

    async def close(self) -> None:
        self.closed += 1


def config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "bot": {"discord_token": "token"},
            "lavalink": {"password": "password", "retry_delay_seconds": 0.1},
        }
    )


def test_discord_bot_is_slash_only_without_privileged_intent() -> None:
    bot = DefaultDiscordBot()
    assert bot.intents.message_content is False
    assert bot.help_command is None
    assert list(bot.walk_commands()) == []


async def test_runtime_starts_syncs_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = FakeBot()
    audio = FakeAudioBackend()
    audio.ready = False
    settings = FakeSettingsRepository()
    presenter = FakePresenter()
    commands = Lifecycle()
    radios = Lifecycle()
    health = Lifecycle()
    players = Lifecycle()
    runtime = DefaultBotRuntime(
        bot,  # type: ignore[arg-type]
        config(),
        audio,
        players,  # type: ignore[arg-type]
        settings,
        radios,  # type: ignore[arg-type]
        presenter,
        commands,  # type: ignore[arg-type]
        commands,  # type: ignore[arg-type]
        commands,  # type: ignore[arg-type]
        health,  # type: ignore[arg-type]
    )
    await runtime.start()
    assert commands.started == 3
    assert bot.synced == [{}]
    assert presenter.client is bot
    assert settings.is_ready() is False
    assert bot.closed is True
    assert health.closed == 1
    assert players.closed == 1
    assert radios.closed == 1


async def test_runtime_guild_sync_and_audio_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    app_config = config()
    app_config.bot.command_sync_guild_id = 123
    bot = FakeBot()
    audio = FakeAudioBackend()
    audio.ready = False
    attempts = 0

    async def start(client: Any) -> None:
        nonlocal attempts
        del client
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first attempt")
        audio.ready = True

    audio.start = start
    settings = FakeSettingsRepository()
    lifecycle = Lifecycle()
    radios = Lifecycle()
    runtime = DefaultBotRuntime(
        bot,  # type: ignore[arg-type]
        app_config,
        audio,
        lifecycle,  # type: ignore[arg-type]
        settings,
        radios,  # type: ignore[arg-type]
        FakePresenter(),
        lifecycle,  # type: ignore[arg-type]
        lifecycle,  # type: ignore[arg-type]
        lifecycle,  # type: ignore[arg-type]
        lifecycle,  # type: ignore[arg-type]
    )
    sleep_calls = 0

    async def sleep(delay: float) -> None:
        nonlocal sleep_calls
        del delay
        sleep_calls += 1

    monkeypatch.setattr(asyncio, "sleep", sleep)
    await runtime._connect_audio()
    await runtime._sync_commands()
    await runtime._sync_commands()
    assert attempts == 2
    assert sleep_calls == 1
    assert len(bot.synced) == 1
