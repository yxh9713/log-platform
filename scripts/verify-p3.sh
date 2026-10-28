#!/bin/sh
set -eu
# All backend tests, including opt-in PostgreSQL/Redis authentication integration.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider
