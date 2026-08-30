# Security policy

Please report suspected vulnerabilities privately through GitHub's security advisory feature rather
than a public issue. Include affected versions, reproduction details, and likely impact.

Never include Discord tokens, Lavalink passwords, Spotify credentials, cookies, or exported account
data in an issue or log excerpt. Rotate any credential that may have been exposed.

The project supports the latest tagged release. Self-hosters should keep DizzyBot, Lavalink, its
plugins, and the base container images current and should not publish the Lavalink port to untrusted
networks.

Saved radio stations cause Lavalink to connect to operator-provided URLs. Adding and removing
stations is therefore restricted to Discord administrators and the configured DJ role. DizzyBot
accepts only HTTP(S) URLs which resolve to public addresses by default; private, loopback,
link-local, reserved, and credential-bearing URLs are rejected. Self-hosters may deliberately opt
in to private-network radio URLs with `bot.allow_private_radio_streams`, but should do so only on a
trusted Discord server because it permits the audio container to reach internal services.
