from pathlib import Path

import pytest
from pydantic import ValidationError

from dizzybot.config import format_validation_error, load_config
from dizzybot.domain import Source


def test_load_config_with_yaml_environment_and_secret_files(tmp_path: Path) -> None:
    token_file = tmp_path / "discord-token"
    token_file.write_text("discord-secret\n", encoding="utf-8")
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """
bot:
  discord_token: replaced
  default_volume: 25
lavalink:
  password: yaml-password
""",
        encoding="utf-8",
    )

    config = load_config(
        config_file,
        environment={
            "DISCORD_TOKEN_FILE": str(token_file),
            "LAVALINK_PASSWORD": "env-password",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
            "TIDAL_TOKEN": "tidal-token",
            "DIZZYBOT__BOT__DEFAULT_VOLUME": "80",
            "DIZZYBOT__BOT__STAY_CONNECTED": "true",
            "DIZZYBOT__BOT__RADIO_STATION_LIMIT": "25",
            "DIZZYBOT__BOT__REPOST_PLAYER_CONTROLS": "false",
            "DIZZYBOT__BOT__DEFAULT_SEARCH_SOURCE": "soundcloud",
        },
    )

    assert config.bot.discord_token.get_secret_value() == "discord-secret"
    assert config.lavalink.password.get_secret_value() == "env-password"
    assert config.bot.default_volume == 80
    assert config.bot.stay_connected is True
    assert config.bot.radio_station_limit == 25
    assert config.bot.repost_player_controls is False
    assert config.bot.default_search_source is Source.SOUNDCLOUD
    assert config.spotify.configured is True
    assert config.tidal.configured is True


def test_spotify_requires_both_credentials(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "bot: {discord_token: token}\nlavalink: {password: pass}", encoding="utf-8"
    )

    config = load_config(config_file, environment={"SPOTIFY_CLIENT_ID": "spotify-id"})

    assert config.spotify.configured is False
    assert config.bot.repost_player_controls is True


def test_tidal_requires_non_empty_token(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    token_file = tmp_path / "tidal-token"
    token_file.write_text("tidal-token\n", encoding="utf-8")
    config_file.write_text(
        "bot: {discord_token: token}\nlavalink: {password: pass}", encoding="utf-8"
    )

    empty = load_config(config_file, environment={"TIDAL_TOKEN": " "})
    config = load_config(config_file, environment={"TIDAL_TOKEN_FILE": str(token_file)})

    assert empty.tidal.configured is False
    assert config.tidal.configured is True


def test_load_config_rejects_invalid_values_and_formats_error(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "bot: {discord_token: token, default_volume: 200}\nlavalink: {password: pass}",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as caught:
        load_config(config_file, environment={})
    assert "bot.default_volume" in format_validation_error(caught.value)


def test_load_config_rejects_non_mapping_and_auto_default(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.yml"
    invalid.write_text("- list", encoding="utf-8")
    with pytest.raises(ValueError, match="root must be a mapping"):
        load_config(invalid, environment={})

    auto = tmp_path / "auto.yml"
    auto.write_text(
        "bot: {discord_token: token, default_search_source: auto}\nlavalink: {password: pass}",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="cannot be auto"):
        load_config(auto, environment={})
