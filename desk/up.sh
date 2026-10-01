#!/usr/bin/env bash
# Start the desk. Generates the homeserver's keys and base config on first run.
set -euo pipefail
cd "$(dirname "$0")"
SERVER_NAME="${FRONTDESK_SERVER_NAME:-frontdesk.localhost}"
if ! docker compose run --rm --no-deps --entrypoint test synapse -f /data/homeserver.yaml 2>/dev/null; then
  docker compose run --rm --no-deps \
    -e SYNAPSE_SERVER_NAME="$SERVER_NAME" -e SYNAPSE_REPORT_STATS=no synapse generate
fi
docker compose up -d --wait
echo "desk is up at http://127.0.0.1:${FRONTDESK_PORT:-8008} (server name $SERVER_NAME)"
