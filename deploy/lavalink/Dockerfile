# syntax=docker/dockerfile:1.7
FROM --platform=$BUILDPLATFORM alpine:3.22 AS ytdlp

ARG TARGETARCH
ARG YT_DLP_VERSION=2026.08.19
RUN case "${TARGETARCH}" in \
      amd64) yt_dlp_asset="yt-dlp_linux"; yt_dlp_sha="58162f9bfdc27458ea47bfcb311cf47028f17d8154a8bf7d689861d46399230a" ;; \
      arm64) yt_dlp_asset="yt-dlp_linux_aarch64"; yt_dlp_sha="b16e4dab368a816cd05d477d698a605a6ae87ccee1c8ffd38fa21d7254141fcc" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && wget --quiet \
      "https://github.com/yt-dlp/yt-dlp/releases/download/${YT_DLP_VERSION}/${yt_dlp_asset}" \
      --output-document /yt-dlp \
    && echo "${yt_dlp_sha}  /yt-dlp" | sha256sum -c \
    && chmod 0555 /yt-dlp

FROM denoland/deno:bin-2.9.5 AS deno

FROM ghcr.io/lavalink-devs/lavalink:4.2.2

USER root
COPY --from=ytdlp /yt-dlp /usr/local/bin/yt-dlp
COPY --from=deno /deno /usr/local/bin/deno
COPY --chown=lavalink:lavalink application.yml /opt/Lavalink/application.yml
COPY --chown=lavalink:lavalink entrypoint.sh /usr/local/bin/dizzybot-lavalink-entrypoint.sh
COPY --chown=lavalink:lavalink healthcheck.sh /usr/local/bin/dizzybot-lavalink-healthcheck.sh
RUN chmod 0555 /usr/local/bin/dizzybot-lavalink-entrypoint.sh \
    /usr/local/bin/dizzybot-lavalink-healthcheck.sh

USER lavalink
WORKDIR /opt/Lavalink
EXPOSE 2333
HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 \
  CMD ["/usr/local/bin/dizzybot-lavalink-healthcheck.sh"]
ENTRYPOINT ["/usr/local/bin/dizzybot-lavalink-entrypoint.sh"]
