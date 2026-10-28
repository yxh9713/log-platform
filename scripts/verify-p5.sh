#!/bin/sh
set -eu
# P5 query/filter/Search/detail checks plus all prior PostgreSQL/Redis regressions.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider
