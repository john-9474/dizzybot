"""Validated YAML configuration with environment and secret-file overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from dizzybot.domain import Source


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discord_token: SecretStr
    default_volume: int = Field(default=75, ge=0, le=100)
    idle_timeout_seconds: int = Field(default=300, ge=30, le=86400)
    stay_connected: bool = False
    default_search_source: Source = Source.YOUTUBE
    playlist_track_limit: int = Field(default=100, ge=1, le=500)
    queue_track_limit: int = Field(default=500, ge=1, le=500)
    radio_station_limit: int = Field(default=50, ge=1, le=100)
    allow_private_radio_streams: bool = False
    command_sync_guild_id: int | None = None

    @field_validator("default_search_source")
    @classmethod
    def playable_default(cls, value: Source) -> Source:
        if value in {Source.AUTO, Source.RADIO}:
            raise ValueError("default_search_source cannot be auto or radio")
        return value


class LavalinkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: str = "http://lavalink:2333"
    password: SecretStr
    identifier: str = "dizzybot"
    connect_retries: int = Field(default=10, ge=1, le=100)
    retry_delay_seconds: float = Field(default=3.0, ge=0.1, le=60)


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "sqlite+aiosqlite:////data/dizzybot.sqlite3"


class HealthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"


class SpotifyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: SecretStr | None = None
    client_secret: SecretStr | None = None

    @property
    def configured(self) -> bool:
        if self.client_id is None or self.client_secret is None:
            return False
        return bool(
            self.client_id.get_secret_value().strip()
            and self.client_secret.get_secret_value().strip()
        )


class TidalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token is not None and self.token.get_secret_value().strip())


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot: BotConfig
    lavalink: LavalinkConfig
    database: DatabaseConfig = DatabaseConfig()
    health: HealthConfig = HealthConfig()
    logging: LoggingConfig = LoggingConfig()
    spotify: SpotifyConfig = SpotifyConfig()
    tidal: TidalConfig = TidalConfig()


_DIRECT_SECRETS = {
    "DISCORD_TOKEN": ("bot", "discord_token"),
    "LAVALINK_PASSWORD": ("lavalink", "password"),
    "SPOTIFY_CLIENT_ID": ("spotify", "client_id"),
    "SPOTIFY_CLIENT_SECRET": ("spotify", "client_secret"),
    "TIDAL_TOKEN": ("tidal", "token"),
}


def _parse_scalar(value: str) -> Any:
    parsed = yaml.safe_load(value)
    return value if parsed is None and value.lower() not in {"null", "~"} else parsed


def _read_secret(name: str, environment: dict[str, str]) -> str | None:
    file_name = environment.get(f"{name}_FILE")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return environment.get(name)


def _set_nested(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = data
    for part in path[:-1]:
        child = cursor.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"Cannot override non-mapping setting: {'.'.join(path)}")
        cursor = child
    cursor[path[-1]] = value


def load_config(
    path: str | Path | None = None,
    *,
    environment: dict[str, str] | None = None,
) -> AppConfig:
    env = dict(os.environ if environment is None else environment)
    config_path = Path(path or env.get("DIZZYBOT_CONFIG", "config.yml"))
    data: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("The configuration root must be a mapping")
        data = loaded

    for name, setting_path in _DIRECT_SECRETS.items():
        secret = _read_secret(name, env)
        if secret is not None:
            _set_nested(data, setting_path, secret)

    prefix = "DIZZYBOT__"
    for name, raw_value in env.items():
        if name.startswith(prefix):
            setting_path = tuple(part.lower() for part in name[len(prefix) :].split("__"))
            _set_nested(data, setting_path, _parse_scalar(raw_value))

    return AppConfig.model_validate(data)


def format_validation_error(error: ValidationError) -> str:
    messages = []
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"])
        messages.append(f"{location}: {issue['msg']}")
    return "\n".join(messages)
