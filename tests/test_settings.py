from pathlib import Path

from dizzybot.defaults.settings import DefaultSettingsRepository
from dizzybot.domain import GuildSettings, Source


async def test_sqlite_settings_persist_and_reset(tmp_path: Path) -> None:
    database = tmp_path / "settings.sqlite3"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    repository = DefaultSettingsRepository(
        url,
        default_volume=70,
        default_idle_timeout_seconds=400,
        default_stay_connected=False,
        default_search_source=Source.SOUNDCLOUD,
    )
    assert repository.is_ready() is False
    await repository.start()
    assert repository.is_ready() is True
    assert await repository.get(123) == GuildSettings(
        guild_id=123,
        default_volume=70,
        idle_timeout_seconds=400,
        default_search_source=Source.SOUNDCLOUD,
    )
    saved = GuildSettings(
        guild_id=123,
        default_volume=20,
        idle_timeout_seconds=60,
        stay_connected=True,
        dj_role_id=456,
        default_search_source=Source.SPOTIFY,
    )
    await repository.save(saved)
    await repository.close()

    reopened = DefaultSettingsRepository(
        url,
        default_volume=75,
        default_idle_timeout_seconds=300,
        default_stay_connected=False,
        default_search_source=Source.YOUTUBE,
    )
    await reopened.start()
    assert await reopened.get(123) == saved
    assert await reopened.reset(123) == GuildSettings(guild_id=123)
    assert await reopened.get(123) == GuildSettings(guild_id=123)
    await reopened.close()
