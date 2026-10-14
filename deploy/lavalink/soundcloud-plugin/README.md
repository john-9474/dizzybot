# DizzyBot SoundCloud source

This plugin adds SoundCloud's AAC/fMP4 HLS streams to the LavaPlayer version shipped by Lavalink
4.2.2. Both DizzyBot audio images compile and include it. It uses Lavalink's public source-plugin
interface; the original `lavalink.server.sources.soundcloud` must be `false` to avoid registering
two sources with the same name. The existing search and preview-filter settings still apply.

The plugin reuses the upstream SoundCloud metadata, URL, search, set, and client-ID loaders. It
adds one format identifier (`A:`), preserving the `soundcloud` source name and existing MP3/Opus
identifiers. Encoded tracks and playlist selections round-trip through Lavalink normally.

AAC playback reads the HLS initialization segment and successive MP4 fragments directly into
LavaPlayer's existing MP4 reader and AAC decoder. Seeking starts at the appropriate segment and
discards samples up to the requested time. Signed URLs are renewed every ten minutes without
changing the timeline. A separate, cookieless media client preserves CDN signatures: the upstream
API client would append `client_id` to SoundCloud's new CDN URLs and invalidate them.

No media files are saved, no external transcoder is invoked, and no credentials are added. This
implementation handles the finite, unencrypted fMP4 media playlists currently returned by
SoundCloud. It reports an error for encrypted media, byte ranges, discontinuities, changing
initialization segments, and master/live playlists rather than treating them as this format.

Build and run deterministic regression tests with Java 17+ and Maven 3.9.11:

```sh
mvn -B -ntp -f deploy/lavalink/soundcloud-plugin/pom.xml verify
```

The artifact is `target/dizzybot-soundcloud.jar` inside this directory. To check real SoundCloud
loading, audio decoding, segment transitions, seeking, natural completion, and replay:

```sh
mvn -B -ntp -f deploy/lavalink/soundcloud-plugin/pom.xml -Ddizzybot.live=true test
```

The optional live test uses `https://soundcloud.com/mtrn/chavvy-wobblaz` by default. Override it
with `-Ddizzybot.liveUrl=...` using an AAC track longer than 90 seconds. It consumes Opus frames in
memory and needs neither a Discord token nor a voice connection. It is excluded from required CI
because provider availability is nondeterministic.

When updating Lavalink, review its LavaPlayer version and the source-plugin API, run the Java tests
and optional live check, and verify that `/v4/info` lists this plugin and exactly one `soundcloud`
source alongside LavaSrc. The plugin deliberately supplies no copy of LavaPlayer or Spring in its
jar. Remove it once the bundled upstream SoundCloud source provides equivalent support.
