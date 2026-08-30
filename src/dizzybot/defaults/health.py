from __future__ import annotations

from collections.abc import Callable

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

from dizzybot.config import HealthConfig
from dizzybot.contracts import BaseHealthService
from dizzybot.domain import HealthSnapshot


class ErrorOnlyAccessLogger(AbstractAccessLogger):
    """Keep successful Docker probes quiet while retaining failed HTTP requests."""

    def log(self, request: web.BaseRequest, response: web.StreamResponse, time: float) -> None:
        if response.status >= 400:
            self.logger.warning(
                "%s %s returned %d in %.3fs",
                request.method,
                request.path,
                response.status,
                time,
            )


class DefaultHealthService(BaseHealthService):
    def __init__(
        self,
        config: HealthConfig,
        *,
        discord_ready: Callable[[], bool],
        audio_ready: Callable[[], bool],
        storage_ready: Callable[[], bool],
    ) -> None:
        self._config = config
        self._discord_ready = discord_ready
        self._audio_ready = audio_ready
        self._storage_ready = storage_ready
        self._runner: web.AppRunner | None = None

    def snapshot(self) -> HealthSnapshot:
        discord_ready = self._discord_ready()
        audio_ready = self._audio_ready()
        storage_ready = self._storage_ready()
        return HealthSnapshot(
            live=True,
            ready=discord_ready and audio_ready and storage_ready,
            discord_ready=discord_ready,
            audio_ready=audio_ready,
            storage_ready=storage_ready,
        )

    async def _live(self, request: web.Request) -> web.Response:
        del request
        return web.json_response({"live": True})

    async def _ready(self, request: web.Request) -> web.Response:
        del request
        snapshot = self.snapshot()
        status = 200 if snapshot.ready else 503
        return web.json_response(
            {
                "ready": snapshot.ready,
                "discord": snapshot.discord_ready,
                "audio": snapshot.audio_ready,
                "storage": snapshot.storage_ready,
            },
            status=status,
        )

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/health/live", self._live)
        app.router.add_get("/health/ready", self._ready)
        self._runner = web.AppRunner(app, access_log_class=ErrorOnlyAccessLogger)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._config.host, self._config.port)
        await site.start()

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
