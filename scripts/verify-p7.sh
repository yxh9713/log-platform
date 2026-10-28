#!/bin/sh
set -eu
# Full manifest intake, database recovery and prior-slice regressions.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider
sh scripts/verify.sh
