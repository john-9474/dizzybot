from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic.config import Config as AlembicConfig
from sqlalchemy import BigInteger, String, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from alembic import command
from dizzybot.contracts import BaseRadioRepository
from dizzybot.defaults.settings import Base
from dizzybot.domain import RadioStation
from dizzybot.errors import InvalidRequestError


def normalize_radio_name(name: str) -> tuple[str, str]:
    display_name = " ".join(name.split())
    if not 1 <= len(display_name) <= 50:
        raise InvalidRequestError("A radio station name must be between 1 and 50 characters.")
    return display_name, display_name.casefold()


class RadioStationRow(Base):
    __tablename__ = "radio_stations"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)


class DefaultRadioRepository(BaseRadioRepository):
    def __init__(self, database_url: str, *, migrations_path: Path | None = None) -> None:
        self._database_url = database_url
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

    def _session_factory(self) -> async_sessionmaker[Any]:
        if self._sessions is None:
            raise RuntimeError("Radio repository has not been started")
        return self._sessions

    @staticmethod
    def _station(row: RadioStationRow) -> RadioStation:
        return RadioStation(guild_id=row.guild_id, name=row.name, url=row.url)

    async def add(self, station: RadioStation) -> RadioStation:
        display_name, name_key = normalize_radio_name(station.name)
        if not 1 <= len(station.url) <= 2048:
            raise InvalidRequestError("The radio stream URL must be between 1 and 2048 characters.")
        saved = RadioStation(guild_id=station.guild_id, name=display_name, url=station.url)
        async with self._session_factory()() as session:
            session.add(
                RadioStationRow(
                    guild_id=saved.guild_id,
                    name_key=name_key,
                    name=saved.name,
                    url=saved.url,
                )
            )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise InvalidRequestError(
                    f'A radio station named "{display_name}" already exists.'
                ) from error
        return saved

    async def get(self, guild_id: int, name: str) -> RadioStation | None:
        _, name_key = normalize_radio_name(name)
        async with self._session_factory()() as session:
            row = await session.get(
                RadioStationRow,
                {"guild_id": guild_id, "name_key": name_key},
            )
            return None if row is None else self._station(row)

    async def list(self, guild_id: int) -> tuple[RadioStation, ...]:
        async with self._session_factory()() as session:
            rows = (
                await session.scalars(
                    select(RadioStationRow)
                    .where(RadioStationRow.guild_id == guild_id)
                    .order_by(RadioStationRow.name_key)
                )
            ).all()
            return tuple(self._station(row) for row in rows)

    async def remove(self, guild_id: int, name: str) -> RadioStation | None:
        station = await self.get(guild_id, name)
        if station is None:
            return None
        _, name_key = normalize_radio_name(name)
        async with self._session_factory()() as session:
            await session.execute(
                delete(RadioStationRow).where(
                    RadioStationRow.guild_id == guild_id,
                    RadioStationRow.name_key == name_key,
                )
            )
            await session.commit()
        return station
