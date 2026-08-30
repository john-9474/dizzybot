from __future__ import annotations

from dizzybot.composition import build_services
from dizzybot.config import AppConfig
from dizzybot.contracts import BaseQueue
from dizzybot.defaults.queue import DefaultQueue
from dizzybot.domain import Track


def test_composition_builds_default_contracts() -> None:
    config = AppConfig.model_validate(
        {
            "bot": {"discord_token": "token"},
            "lavalink": {"password": "password"},
            "database": {"url": "sqlite+aiosqlite:///:memory:"},
            "health": {"host": "127.0.0.1", "port": 9999},
        }
    )
    services = build_services(config)
    assert services.audio.is_ready() is False
    assert services.presenter is not None
    assert services.controls is not None
    assert services.radios.is_ready() is False
    assert services.radio_resolver is not None
    assert services.radio_commands is not None
    assert services.runtime is not None


def test_fork_can_replace_queue_at_composition_point() -> None:
    class CustomQueue(DefaultQueue):
        def enqueue(self, tracks: tuple[Track, ...]) -> None:
            super().enqueue(tuple(reversed(tracks)))

    queue: BaseQueue = CustomQueue()
    assert isinstance(queue, DefaultQueue)
