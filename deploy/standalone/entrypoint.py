#!/usr/bin/env python3
"""Run DizzyBot and its private Lavalink node as one container."""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

_SECRET_NAMES = (
    "DISCORD_TOKEN",
    "LAVALINK_PASSWORD",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "TIDAL_TOKEN",
)


def _load_file_secret(name: str) -> None:
    secret_file = os.environ.get(f"{name}_FILE")
    if not secret_file:
        return
    path = Path(secret_file)
    try:
        os.environ[name] = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise SystemExit(f"Secret file for {name} cannot be read: {path}: {error}") from error


def _configure_environment() -> None:
    for name in _SECRET_NAMES:
        _load_file_secret(name)

    if not os.environ.get("DISCORD_TOKEN"):
        raise SystemExit("DISCORD_TOKEN or DISCORD_TOKEN_FILE is required")

    # Lavalink is private to this container, so operators do not need to manage
    # a second credential. A new shared password is safe to generate each start.
    if not os.environ.get("LAVALINK_PASSWORD"):
        os.environ["LAVALINK_PASSWORD"] = secrets.token_urlsafe(32)

    spotify_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    spotify_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if spotify_id and spotify_secret:
        os.environ["LAVASRC_SPOTIFY_CONFIGURED"] = "true"
    else:
        os.environ.pop("LAVASRC_SPOTIFY_CONFIGURED", None)
        if spotify_id or spotify_secret:
            print(
                "Spotify is disabled because both SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET are required.",
                file=sys.stderr,
                flush=True,
            )

    optional_sources = (("TIDAL_TOKEN", "LAVASRC_TIDAL_CONFIGURED"),)
    for token_name, enabled_name in optional_sources:
        if os.environ.get(token_name, "").strip():
            os.environ[enabled_name] = "true"
        else:
            os.environ.pop(enabled_name, None)


def _runtime_ids() -> tuple[int, int]:
    try:
        uid = int(os.environ.get("PUID", "99"))
        gid = int(os.environ.get("PGID", "100"))
    except ValueError as error:
        raise SystemExit("PUID and PGID must be positive integers") from error
    if uid < 1 or gid < 1:
        raise SystemExit("PUID and PGID must be positive integers")
    return uid, gid


def _prepare_writable_paths(uid: int, gid: int) -> None:
    for base in (Path("/data"), Path("/opt/Lavalink")):
        for directory, names, filenames in os.walk(base):
            os.chown(directory, uid, gid)
            for name in (*names, *filenames):
                path = Path(directory, name)
                if not path.is_symlink():
                    os.chown(path, uid, gid)


def _terminate(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for _, process in processes:
        if process.poll() is None:
            process.terminate()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and any(process.poll() is None for _, process in processes):
        time.sleep(0.1)

    for _, process in processes:
        if process.poll() is None:
            process.kill()
        process.wait()


def main() -> int:
    _configure_environment()
    uid, gid = _runtime_ids()
    _prepare_writable_paths(uid, gid)
    os.environ["HOME"] = "/data"
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        processes.append(
            (
                "Lavalink",
                subprocess.Popen(
                    ["java", "-jar", "/opt/Lavalink/Lavalink.jar"],
                    cwd="/opt/Lavalink",
                    user=uid,
                    group=gid,
                ),
            )
        )
        processes.append(
            (
                "DizzyBot",
                subprocess.Popen(
                    ["dizzybot", "--config", os.environ["DIZZYBOT_CONFIG"]],
                    cwd="/app",
                    user=uid,
                    group=gid,
                ),
            )
        )

        exit_code = 0
        while not stopping:
            for name, process in processes:
                result = process.poll()
                if result is not None:
                    print(
                        f"{name} exited with status {result}; stopping the container.",
                        file=sys.stderr,
                        flush=True,
                    )
                    exit_code = result or 1
                    stopping = True
                    break
            if not stopping:
                time.sleep(0.25)
        return exit_code
    finally:
        _terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
