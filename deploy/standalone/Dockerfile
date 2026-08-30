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

FROM python:3.13-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv export --frozen --no-dev --no-emit-project --output-file requirements.txt \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels --no-deps .

FROM ghcr.io/lavalink-devs/lavalink:4.2.2 AS lavalink

FROM denoland/deno:bin-2.9.5 AS deno

FROM python:3.13-slim-bookworm

ARG VERSION=dev
LABEL org.opencontainers.image.title="DizzyBot Standalone" \
      org.opencontainers.image.description="DizzyBot and Lavalink in one self-hosted container" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/john-9474/dizzybot"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DIZZYBOT_CONFIG=/etc/dizzybot/config.yml \
    DIZZYBOT__LAVALINK__URI=http://127.0.0.1:2333 \
    LAVALINK_SERVER_ADDRESS=127.0.0.1 \
    _JAVA_OPTIONS="-Xms128m -Xmx1g"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dizzybot \
    && useradd --uid 10001 --gid dizzybot --system --create-home dizzybot \
    && mkdir -p /app /data /etc/dizzybot /opt/Lavalink/plugins \
    && chown -R dizzybot:dizzybot /app /data /etc/dizzybot /opt/Lavalink

COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY --from=lavalink --chown=dizzybot:dizzybot /opt/Lavalink/Lavalink.jar /opt/Lavalink/
COPY --from=ytdlp /yt-dlp /usr/local/bin/yt-dlp
COPY --from=deno /deno /usr/local/bin/deno
COPY --chown=dizzybot:dizzybot deploy/lavalink/application.yml /opt/Lavalink/application.yml
COPY --chown=dizzybot:dizzybot config.example.yml /etc/dizzybot/config.yml
COPY --chown=root:root deploy/standalone/entrypoint.py /usr/local/bin/dizzybot-standalone
RUN chmod 0555 /usr/local/bin/dizzybot-standalone

WORKDIR /app
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3)"]
ENTRYPOINT ["/usr/local/bin/dizzybot-standalone"]
