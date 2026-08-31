# syntax=docker/dockerfile:1.7
FROM python:3.14-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv export --frozen --no-dev --no-emit-project --output-file requirements.txt \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels --no-deps .

FROM python:3.14-slim

ARG VERSION=dev
LABEL org.opencontainers.image.title="DizzyBot" \
      org.opencontainers.image.description="Extensible self-hosted Discord music bot" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/john-9474/dizzybot"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DIZZYBOT_CONFIG=/etc/dizzybot/config.yml

RUN groupadd --gid 10001 dizzybot \
    && useradd --uid 10001 --gid dizzybot --system --create-home dizzybot \
    && mkdir -p /data /etc/dizzybot \
    && chown -R dizzybot:dizzybot /data /etc/dizzybot

COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY config.example.yml /etc/dizzybot/config.yml
WORKDIR /app
USER dizzybot
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3)"]
ENTRYPOINT ["dizzybot"]
CMD ["--config", "/etc/dizzybot/config.yml"]
