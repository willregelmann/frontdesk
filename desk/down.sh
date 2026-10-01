#!/usr/bin/env bash
# Stop the desk. Pass --wipe to also delete every identity, channel and message.
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" = "--wipe" ]; then docker compose down -v; else docker compose down; fi
