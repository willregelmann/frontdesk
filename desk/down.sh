#!/usr/bin/env bash
# Stop the desk. Pass --wipe to also delete every identity, channel and message.
set -euo pipefail
cd "$(dirname "$0")"
# --test: the throwaway desk from `up.sh --test`. --wipe: also delete every identity, channel and message.
for arg in "$@"; do [ "$arg" = "--test" ] && export COMPOSE_PROJECT_NAME=frontdesk-test; done
case " $* " in *" --wipe "*) docker compose down -v ;; *) docker compose down ;; esac
