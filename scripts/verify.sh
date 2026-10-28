#!/bin/sh
set -eu
# Run after docker compose up --build --wait. Source mounts remain read-only.
docker compose exec -T api ruff check --no-cache app tests alembic
docker compose exec -T api ruff format --check --no-cache app tests alembic
docker compose exec -T api mypy --cache-dir=/tmp/logistics-mypy app tests alembic
docker compose exec -T api pytest -q -p no:cacheprovider
docker compose exec -T frontend npm run format:check
docker compose exec -T frontend npm run lint
docker compose exec -T frontend npm run typecheck
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
python3 scripts/smoke.py
