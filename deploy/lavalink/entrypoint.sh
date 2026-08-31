#!/bin/sh
set -eu

load_secret() {
  secret_name="$1"
  eval "secret_file=\${${secret_name}_FILE:-}"
  if [ -n "$secret_file" ]; then
    if [ ! -r "$secret_file" ]; then
      echo "Secret file for $secret_name is not readable: $secret_file" >&2
      exit 1
    fi
    secret_value="$(tr -d '\r\n' < "$secret_file")"
    export "$secret_name=$secret_value"
  fi
}

load_secret LAVALINK_PASSWORD
load_secret SPOTIFY_CLIENT_ID
load_secret SPOTIFY_CLIENT_SECRET
load_secret TIDAL_TOKEN

if [ -n "${SPOTIFY_CLIENT_ID:-}" ] && [ -n "${SPOTIFY_CLIENT_SECRET:-}" ]; then
  export LAVASRC_SPOTIFY_CONFIGURED=true
fi

if [ -n "${TIDAL_TOKEN:-}" ]; then
  export LAVASRC_TIDAL_CONFIGURED=true
fi

if [ -z "${LAVALINK_PASSWORD:-}" ]; then
  echo "LAVALINK_PASSWORD or LAVALINK_PASSWORD_FILE is required" >&2
  exit 1
fi

exec java -jar Lavalink.jar
