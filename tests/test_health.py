from __future__ import annotations

import logging
import socket

import aiohttp
import pytest

from dizzybot.config import HealthConfig
from dizzybot.defaults.health import DefaultHealthService


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_health_live_and_ready_endpoints(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="aiohttp.access")
    state = {"discord": False, "audio": True, "storage": True}
    port = free_port()
    health = DefaultHealthService(
        HealthConfig(host="127.0.0.1", port=port),
        discord_ready=lambda: state["discord"],
        audio_ready=lambda: state["audio"],
        storage_ready=lambda: state["storage"],
    )
    assert health.snapshot().ready is False
    await health.start()
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}/health/live") as response:
            assert response.status == 200
            assert await response.json() == {"live": True}
        async with session.get(f"http://127.0.0.1:{port}/health/ready") as response:
            assert response.status == 503
            payload = await response.json()
            assert payload["discord"] is False
        state["discord"] = True
        async with session.get(f"http://127.0.0.1:{port}/health/ready") as response:
            assert response.status == 200
            assert (await response.json())["ready"] is True
    access_records = [record for record in caplog.records if record.name == "aiohttp.access"]
    assert len(access_records) == 1
    assert "503" in access_records[0].getMessage()
    await health.close()
    await health.close()
