#!/bin/sh
set -eu
# P6 UI and API regressions, with real PostgreSQL/Redis isolation checks.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider
sh scripts/verify.sh
