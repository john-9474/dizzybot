#!/bin/sh
set -eu

password="${LAVALINK_PASSWORD:-}"
if [ -n "${LAVALINK_PASSWORD_FILE:-}" ]; then
  password="$(tr -d '\r\n' < "$LAVALINK_PASSWORD_FILE")"
fi

curl --fail --silent --show-error \
  --header "Authorization: $password" \
  http://127.0.0.1:2333/version >/dev/null
