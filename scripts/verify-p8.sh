#!/bin/sh
set -eu
# Carrier authentication, event ordering, CSV recovery and prior-slice regressions.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider --tb=short
sh scripts/verify.sh
