#!/bin/sh
set -eu
# My Day aggregate/security fixtures and all prior application regressions.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider --tb=short
sh scripts/verify.sh
