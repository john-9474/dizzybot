# DizzyBot

DizzyBot is a fully open-source, self-hosted Discord music bot written in Python. It uses
[Lavalink](https://lavalink.dev/) for voice playback and is designed for Docker hosts, including
Unraid.

The project is deliberately easy to fork. Queueing, source resolution, playback, interactive
controls, permissions, settings, presentation, commands, health checks, and runtime lifecycle all
have public base classes and first-party default subclasses. A single composition module selects the
implementations.

## Features

- YouTube videos and playlists
- YouTube Music links (through the YouTube source)
- SoundCloud tracks and sets
- Spotify track, album, and playlist links mirrored to YouTube or SoundCloud
- Apple Music tracks, albums, and playlists mirrored to YouTube or SoundCloud
- Optional TIDAL tracks, albums, and playlists mirrored to YouTube or SoundCloud
- Bandcamp tracks and albums
- Persistent per-server internet radio stations, with no stations imposed by default
- Slash commands only; no message-content intent
- Independent queues and playback in multiple Discord servers
- Pause, resume, seek, volume, queue editing, shuffle, and track/queue repeat
- An automatically updated Now Playing panel with Previous, Play/Pause, Skip, and Stop buttons
- SQLite-backed per-server settings with automatic migrations
- Configurable same-channel permissions plus administrator/DJ-role overrides
- Configurable idle and empty-channel disconnects, with DJ-controlled 24/7 mode
- Docker health endpoints and pinned Lavalink plugins
- One-container Unraid template with bundled private Lavalink
- Published `linux/amd64` and `linux/arm64` image workflow

Spotify, Apple Music, and TIDAL are metadata sources rather than audio sources. DizzyBot uses
[LavaSrc mirroring](https://github.com/topi314/LavaSrc/blob/4.8.3/README.md): the selected service supplies metadata and
a playable match is found on YouTube or SoundCloud. Bandcamp, YouTube, SoundCloud, and saved radio
streams are relayed directly by Lavalink. Operators must follow the terms of every configured media
service. DizzyBot does not bypass DRM, download media, or cache audio.

## Unraid: one-container installation

Unraid users do not need to clone the repository, manage Compose, create a Lavalink container, or
publish any ports. The Community Applications template deploys
`ghcr.io/john-9474/dizzybot-standalone:latest`, which contains both DizzyBot and its private Lavalink
process.

Once the Community Applications listing is published:

1. Open **Apps** in Unraid and search for **DizzyBot**.
2. Select **Install** and enter the Discord bot token. Spotify and TIDAL credentials are optional;
   Apple Music and Bandcamp work without additional credentials.
3. Select **Apply**. The template creates the appdata mapping and starts the single container.

The standalone image generates its internal Lavalink password automatically. It runs the bot and
Lavalink as Unraid's standard UID/GID `99:100`, persists server settings under
`/mnt/user/appdata/dizzybot`, supervises both processes, and stops the whole container if either one
fails. The source for the listing is [`templates/dizzybot.xml`](templates/dizzybot.xml).

The template and image publication workflow are included in this repository. The listing will become
searchable after a tagged image has been published to the public GHCR package and the template has
passed the Community Applications **Validate and Scan** submission.

## Quick start with Docker Compose

Prerequisites:

- Docker Engine with Docker Compose v2
- A Discord application and bot token
- Optional Spotify developer application for Spotify links
- Optional LavaSrc-compatible TIDAL token for TIDAL links and searches

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an
   application and bot. You do not need to enable Message Content Intent.
2. Generate an invite under **OAuth2 > URL Generator** with the `bot` and
   `applications.commands` scopes. Grant `View Channels`, `Send Messages`, `Embed Links`,
   `Connect`, `Speak`, and `Use Slash Commands`.
3. Clone this repository, copy the environment template, and edit `.env`:

   ```sh
   cp .env.example .env
   ```

   Set `DISCORD_TOKEN` to the bot token and `LAVALINK_PASSWORD` to a long random value. The same
   Lavalink password is passed to both containers automatically. The repository ignores `.env`, but
   you should still restrict access to it and never commit or share it.

4. Start both containers:

   ```sh
   docker compose up --detach --build
   docker compose ps
   ```

The bot and Lavalink communicate over a private Compose network. Lavalink's port and the bot's
health port are not published to the host by default.

For released images, set `DIZZYBOT_VERSION` in `.env`, then run `docker compose pull` followed by
`docker compose up --detach`. The Compose file points to
`ghcr.io/john-9474/dizzybot` and `ghcr.io/john-9474/dizzybot-lavalink`.

## YouTube setup

YouTube playback uses the yt-dlp source built into LavaSrc. The image bundles pinned yt-dlp and Deno
executables for both `linux/amd64` and `linux/arm64`, so no Google account, cookies, converter site, or
extra container is required. yt-dlp resolves the playable stream and Lavalink relays it directly to
Discord; DizzyBot does not save or cache media files.

YouTube changes its playback interface frequently. DizzyBot therefore pins yt-dlp so image builds are
reproducible, while subsequent DizzyBot releases can update the extractor independently of Lavalink.
Occasional videos may still be unavailable because of regional, age, account, or rights restrictions.

## Music sources

YouTube, YouTube Music, SoundCloud, Apple Music, and Bandcamp are available without provider
credentials. Apple Music is a metadata source: the bundled LavaSrc plugin obtains its public media
API token and mirrors matches to YouTube or SoundCloud. Set `APPLE_MUSIC_COUNTRY_CODE` to a
two-letter storefront code if the default `GB` is not appropriate. Bandcamp public tracks and albums
are loaded directly by Lavalink.

For `/play` searches, `source` can be `auto`, `youtube`, `soundcloud`, `spotify`, `apple_music`,
`tidal`, or `bandcamp`. You can also choose any configured source as a server's default with
`/settings search-provider`. A URL automatically selects its matching source regardless of that
default.

### Spotify

Create an application in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
and add these values to `.env`:

```dotenv
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret
SPOTIFY_COUNTRY_CODE=GB
```

Restart the stack after changing these values. Spotify is enabled automatically when both the client
ID and client secret are present. It is optional: without both credentials, YouTube and SoundCloud
remain available and Spotify requests return a configuration error. Current Spotify development-mode
accounts require the application owner to have Premium and are subject to Spotify's user and quota
limits.

### TIDAL

TIDAL support is optional because LavaSrc requires a compatible API token. Add it to `.env` or the
TIDAL Token field in the Unraid template:

```dotenv
TIDAL_TOKEN=your-lavasrc-compatible-token
TIDAL_COUNTRY_CODE=GB
```

Restart the container after changing it. TIDAL activates automatically when the token is non-empty;
without one, its commands return an actionable configuration error and all other sources continue to
work. DizzyBot does not collect TIDAL login details or browser session cookies, and the project does
not issue provider tokens.

The provided Compose stack reads all credentials from `.env`. Both containers also understand
`*_FILE` variants for custom deployments that mount Docker secrets instead; supported names include
`DISCORD_TOKEN_FILE`, `LAVALINK_PASSWORD_FILE`, `SPOTIFY_CLIENT_ID_FILE`, and
`SPOTIFY_CLIENT_SECRET_FILE`, and `TIDAL_TOKEN_FILE`.

Amazon Music and Pandora are not supported by the pinned Lavalink plugins. Deezer, Qobuz, Yandex
Music, VK Music, and JioSaavn are not enabled because their LavaSrc integrations play directly and
may require private account/session credentials, decryption material, or region-specific setup.
They can be evaluated separately in a fork without weakening the default public image.

## Internet radio

DizzyBot can relay direct internet radio streams through Lavalink. It deliberately ships with an
empty station list: each Discord server chooses and names its own stations. For example, a DJ or
administrator can save a Radio.co listen endpoint with:

```text
/radio add name:House Nation url:https://streaming.radio.co/s06bd9d805/listen
```

Then any member who meets the normal voice-channel rules can use `/radio play name:House Nation`.
Both modern HTTPS streams and older HTTP Icecast/SHOUTcast streams are supported. Use the direct
audio endpoint—usually returning a content type such as `audio/mpeg`—rather than a station's web
player page. Plain HTTP works for legacy stations but is not encrypted in transit.

Adding and removing stations requires an administrator or the configured DJ role. This is important
because the saved URL causes the self-hosted audio service to make an outbound connection. URLs with
embedded credentials and URLs resolving to local, private, link-local, or reserved addresses are
blocked by default. A trusted private deployment can opt in with
`bot.allow_private_radio_streams: true`. Radio streams remain subject to the configured idle/empty
channel timeout and 24/7 mode. If an upstream live stream times out or ends unexpectedly, DizzyBot
reloads its media URL and attempts to reconnect up to three times before continuing with the queue.

## Commands

| Command | Behavior |
| --- | --- |
| `/play query [source]` | Search or queue a supported track/playlist URL; joins automatically |
| `/join`, `/leave` | Join, or stop/clear/disconnect |
| `/pause`, `/resume`, `/skip`, `/stop` | Control current playback |
| `/queue [page]`, `/nowplaying` | Inspect playback and the upcoming queue |
| `/remove position`, `/move from_position to_position` | Edit upcoming tracks |
| `/clear`, `/shuffle` | Clear or shuffle upcoming tracks |
| `/repeat mode` | Select `off`, `track`, or `queue` |
| `/volume percent` | Set session volume from 0–100 |
| `/seek position` | Seek using seconds, `MM:SS`, or `HH:MM:SS` |
| `/radio add name url` | Save a direct stream URL (DJ role or administrator) |
| `/radio play name` | Play or queue a saved station; station names autocomplete |
| `/radio list [page]` | List this server's saved stations |
| `/radio remove name` | Remove a saved station (DJ role or administrator) |
| `/settings show` | Display persistent settings (Manage Server required) |
| `/settings volume` | Change the default volume |
| `/settings idle-timeout` | Change empty/idle voice disconnect time from 30–86400 seconds |
| `/settings 24-7` | Enable or disable persistent voice connection (DJ role or administrator) |
| `/settings dj-role` | Set the role allowed to control an active session remotely |
| `/settings search-provider` | Select the default provider for text searches |
| `/settings reset` | Restore all deployment defaults |

Normal members must be in the bot's voice channel. Administrators and the configured DJ role may
control an existing session remotely, but no command silently moves an active player to another voice
channel.

When playback starts, DizzyBot posts one Now Playing panel in the active announcement channel and
edits that message as the session changes. It shows the title, artist, artwork when available,
playback time, requester, source, volume, repeat mode, current queue position, and the playlist name
and playlist position when applicable. The buttons use the same voice-channel and DJ/administrator
rules as slash commands. Previous returns to the last successfully played or manually skipped track;
failed tracks are excluded from history. Panels are disabled when playback stops or the bot leaves.

By default, DizzyBot leaves five minutes after playback becomes idle or the voice channel has no
human listeners. Administrators can change that delay with `/settings idle-timeout`. Members with the
configured DJ role can use `/settings 24-7 enabled:true` to suppress automatic departure, or
`enabled:false` to restore it. Administrators can also toggle 24/7 mode as an emergency override.
24/7 mode keeps an active connection open; it does not restore a voice session after a bot restart.

## Configuration

[`config.example.yml`](config.example.yml) contains every ordinary deployment setting. The container
uses this file by default. To customize it, copy the file and mount it at
`/etc/dizzybot/config.yml:ro`.

Environment variables beginning with `DIZZYBOT__` override nested YAML keys. For example:

```dotenv
DIZZYBOT__BOT__DEFAULT_VOLUME=60
DIZZYBOT__BOT__PLAYLIST_TRACK_LIMIT=200
DIZZYBOT__BOT__RADIO_STATION_LIMIT=25
DIZZYBOT__BOT__COMMAND_SYNC_GUILD_ID=123456789012345678
DIZZYBOT__HEALTH__PORT=8081
```

Precedence is environment override, direct credential/credential file, YAML, then built-in default. Playlist
and total queue limits must be between 1 and 500. A development guild ID makes slash commands sync
immediately to that guild; omit it in production to use global commands.

Persistent server settings and saved radio stations live in `/data/dizzybot.sqlite3`. Queues, voice
sessions, repeat state, and session volume intentionally do not survive restarts. Back up the `/data`
volume before upgrades; database migrations run automatically before Discord connects. The default
radio station limit is 50 per server and can be configured from 1 to 100.

Health endpoints are:

- `/health/live`: the process and HTTP server are running
- `/health/ready`: storage is migrated and Discord and Lavalink are connected

## Customizing a fork

Public contracts are in `src/dizzybot/contracts`, default behavior is in
`src/dizzybot/defaults`, and [`composition.py`](src/dizzybot/composition.py) is the only intended
class-selection point.

For example, a fork can reverse every batch added to a queue:

```python
from dizzybot.defaults.queue import DefaultQueue
from dizzybot.domain import Track


class ReverseQueue(DefaultQueue):
    def enqueue(self, tracks: tuple[Track, ...]) -> None:
        super().enqueue(tuple(reversed(tracks)))
```

Then change only the queue factory in `build_services`:

```python
players = DefaultPlayerManager(
    audio,
    settings,
    presenter,
    player_factory=DefaultGuildPlayer,
    queue_factory=ReverseQueue,
    queue_limit=config.bot.queue_track_limit,
)
```

The same pattern applies to `BaseAudioBackend`, `BaseTrackResolver`, `BaseGuildPlayer`,
`BasePermissionPolicy`, `BaseSettingsRepository`, `BasePresenter`, command bases, the health service,
`BasePlaybackControls`, `BaseRadioRepository`, `BaseRadioResolver`, and runtime. There is
intentionally no dynamic plugin loader or import-path configuration.

## Development

Python 3.13 and [uv](https://docs.astral.sh/uv/) are recommended:

```sh
uv sync --frozen --extra dev
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run pytest
uv run pip-audit
```

Validate a configuration without connecting to Discord:

```sh
DISCORD_TOKEN=dummy LAVALINK_PASSWORD=dummy \
  uv run dizzybot --config config.example.yml --check-config
```

Live provider tests are deliberately not part of required CI because upstream search results and
availability are nondeterministic. Unit and integration tests use recorded payloads and fake service
boundaries. Pull requests build the bot-only, Lavalink, and standalone containers; version tags
publish all three as multi-architecture GHCR images with provenance and an SBOM.

## License

DizzyBot is licensed under [GNU GPL version 3](LICENSE). Lavalink and its plugins are separate
projects distributed under their respective licenses.
