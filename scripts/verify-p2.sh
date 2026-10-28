#!/bin/sh
set -eu
# Uses fresh disposable PostgreSQL databases; never downgrades the development DB.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider
