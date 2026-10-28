#!/bin/sh
set -eu
# PostgreSQL migrations, creation/accounts/areas, concurrency and prior-slice tests.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider
