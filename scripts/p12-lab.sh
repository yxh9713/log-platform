#!/bin/sh
set -eu
# This dedicated file has its own PostgreSQL volume/network/ports and fake credentials.
case "${1:-}" in
  start)
    mkdir -p .local/p12/download
    chmod 750 .local/p12/download
    docker compose -p logistics-p12 -f compose.verification.yaml up -d --wait --wait-timeout 180 postgres redis api frontend
    docker compose -p logistics-p12 -f compose.verification.yaml exec -T api python -m tests.system_setup
    docker compose -p logistics-p12 -f compose.verification.yaml --profile workers up -d --wait --wait-timeout 180
    ;;
  stop)
    docker compose -p logistics-p12 -f compose.verification.yaml --profile workers down --volumes
    ;;
  *) echo 'Usage: sh scripts/p12-lab.sh start|stop'; exit 2 ;;
esac
