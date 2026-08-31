from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _entrypoint_module() -> ModuleType:
    path = ROOT / "deploy" / "standalone" / "entrypoint.py"
    spec = importlib.util.spec_from_file_location("standalone_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unraid_template_deploys_one_combined_container() -> None:
    template = ElementTree.parse(ROOT / "templates" / "dizzybot.xml").getroot()
    assert template.tag == "Container"
    assert template.findtext("Repository") == ("ghcr.io/john-9474/dizzybot-standalone:latest")

    configs = {item.attrib["Target"]: item.attrib for item in template.findall("Config")}
    assert configs["DISCORD_TOKEN"]["Required"] == "true"
    assert configs["DISCORD_TOKEN"]["Mask"] == "true"
    assert configs["TIDAL_TOKEN"]["Required"] == "false"
    assert configs["TIDAL_TOKEN"]["Mask"] == "true"
    assert configs["DIZZYBOT__BOT__REPOST_PLAYER_CONTROLS"]["Default"] == "true"
    assert configs["/data"]["Default"] == "/mnt/user/appdata/dizzybot"
    assert "LAVALINK_PASSWORD" not in configs
    assert not any(item.attrib.get("Type") == "Port" for item in template.findall("Config"))

    dockerfile = (ROOT / "deploy" / "standalone" / "Dockerfile").read_text(encoding="utf-8")
    assert "LAVALINK_SERVER_ADDRESS=127.0.0.1" in dockerfile
    assert "yt-dlp" in dockerfile
    assert "denoland/deno:bin-2.9.5" in dockerfile
    assert "EXPOSE 2333" not in dockerfile

    profile = ElementTree.parse(ROOT / "ca_profile.xml").getroot()
    assert profile.tag == "CommunityApplications"


def test_lavalink_uses_bundled_ytdlp_for_youtube() -> None:
    config = yaml.safe_load(
        (ROOT / "deploy" / "lavalink" / "application.yml").read_text(encoding="utf-8")
    )
    assert config["lavalink"]["server"]["sources"]["youtube"] is False
    assert config["lavalink"]["server"]["sources"]["http"] is True
    assert config["plugins"]["lavasrc"]["sources"]["ytdlp"] is True
    assert config["plugins"]["lavasrc"]["ytdlp"]["path"] == "/usr/local/bin/yt-dlp"
    assert config["lavalink"]["server"]["sources"]["bandcamp"] is True
    assert config["plugins"]["lavasrc"]["sources"]["applemusic"] is True
    assert "LAVASRC_TIDAL_CONFIGURED" in config["plugins"]["lavasrc"]["sources"]["tidal"]


def test_standalone_generates_private_lavalink_password(monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint = _entrypoint_module()
    for name in (
        "DISCORD_TOKEN_FILE",
        "LAVALINK_PASSWORD",
        "LAVALINK_PASSWORD_FILE",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "LAVASRC_SPOTIFY_CONFIGURED",
        "TIDAL_TOKEN",
        "LAVASRC_TIDAL_CONFIGURED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")
    monkeypatch.setattr(entrypoint.secrets, "token_urlsafe", lambda _length: "generated")

    entrypoint._configure_environment()

    assert entrypoint.os.environ["LAVALINK_PASSWORD"] == "generated"
    assert "LAVASRC_SPOTIFY_CONFIGURED" not in entrypoint.os.environ
    assert "LAVASRC_TIDAL_CONFIGURED" not in entrypoint.os.environ


def test_standalone_enables_spotify_from_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint = _entrypoint_module()
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "client-secret")

    entrypoint._configure_environment()

    assert entrypoint.os.environ["LAVASRC_SPOTIFY_CONFIGURED"] == "true"


def test_standalone_enables_tidal_from_token(monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint = _entrypoint_module()
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")
    monkeypatch.setenv("TIDAL_TOKEN", "tidal-token")

    entrypoint._configure_environment()

    assert entrypoint.os.environ["LAVASRC_TIDAL_CONFIGURED"] == "true"
