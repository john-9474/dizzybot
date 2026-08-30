from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import BigInteger, Boolean, Integer, String, delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from dizzybot.contracts import BaseSettingsRepository
from dizzybot.domain import GuildSettings, Source


class Base(DeclarativeBase):
    pass


class GuildSettingsRow(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    default_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    stay_connected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dj_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    default_search_source: Mapped[str] = mapped_column(String(32), nullable=False)


class DefaultSettingsRepository(BaseSettingsRepository):
    def __init__(
        self,
        database_url: str,
        *,
        default_volume: int,
        default_idle_timeout_seconds: int,
        default_stay_connected: bool,
        default_search_source: Source,
        migrations_path: Path | None = None,
    ) -> None:
        self._database_url = database_url
        self._defaults = GuildSettings(
            guild_id=0,
            default_volume=default_volume,
            idle_timeout_seconds=default_idle_timeout_seconds,
            stay_connected=default_stay_connected,
            default_search_source=default_search_source,
        )
        self._migrations_path = (
            migrations_path or Path(__file__).resolve().parents[1] / "migrations"
        )
        self._engine: AsyncEngine | None = None
        self._sessions: async_sessionmaker[Any] | None = None
        self._ready = False

    async def start(self) -> None:
        if self._database_url.startswith("sqlite"):
            database_path = self._database_url.rsplit("/", maxsplit=1)[-1]
            if database_path and database_path != ":memory:":
                Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        config = AlembicConfig()
        config.set_main_option("script_location", str(self._migrations_path))
        config.set_main_option("sqlalchemy.url", self._database_url)
        await asyncio.to_thread(command.upgrade, config, "head")
        self._engine = create_async_engine(self._database_url)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._ready = True

    async def close(self) -> None:
        self._ready = False
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessions = None

    def is_ready(self) -> bool:
        return self._ready

    def _default_for(self, guild_id: int) -> GuildSettings:
        return GuildSettings(
            guild_id=guild_id,
            default_volume=self._defaults.default_volume,
            idle_timeout_seconds=self._defaults.idle_timeout_seconds,
            stay_connected=self._defaults.stay_connected,
            default_search_source=self._defaults.default_search_source,
        )

    def _session_factory(self) -> async_sessionmaker[Any]:
        if self._sessions is None:
            raise RuntimeError("Settings repository has not been started")
        return self._sessions

    async def get(self, guild_id: int) -> GuildSettings:
        async with self._session_factory()() as session:
            row = await session.get(GuildSettingsRow, guild_id)
            if row is None:
                return self._default_for(guild_id)
            return GuildSettings(
                guild_id=row.guild_id,
                default_volume=row.default_volume,
                idle_timeout_seconds=row.idle_timeout_seconds,
                stay_connected=row.stay_connected,
                dj_role_id=row.dj_role_id,
                default_search_source=Source(row.default_search_source),
            )

    async def save(self, settings: GuildSettings) -> GuildSettings:
        async with self._session_factory()() as session:
            row = await session.get(GuildSettingsRow, settings.guild_id)
            if row is None:
                row = GuildSettingsRow(guild_id=settings.guild_id)
                session.add(row)
            row.default_volume = settings.default_volume
            row.idle_timeout_seconds = settings.idle_timeout_seconds
            row.stay_connected = settings.stay_connected
            row.dj_role_id = settings.dj_role_id
            row.default_search_source = settings.default_search_source.value
            await session.commit()
        return settings

    async def reset(self, guild_id: int) -> GuildSettings:
        async with self._session_factory()() as session:
            await session.execute(
                delete(GuildSettingsRow).where(GuildSettingsRow.guild_id == guild_id)
            )
            await session.commit()
        return self._default_for(guild_id)
