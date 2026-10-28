#!/bin/sh
set -eu
# Main suite uses its existing disposable DB harness, never fixture-seeds the tenant.
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider --tb=short
sh scripts/verify.sh
docker compose exec -T api python -m app.ops.cli
