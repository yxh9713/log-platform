"""Read-only aggregate diagnostics. Never emit credentials, paths or payloads."""

import json
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.exports.schema import jobs
from app.ingestion.schema import ingestion_imports, ingestion_source
from app.pod.schema import shipment_images
from app.shipments.schema import ingestion_errors


def diagnose(engine: Engine) -> dict[str, Any]:
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):

        def groups(table: sa.Table, column: str) -> dict[str, int]:
            return dict(
                connection.execute(
                    sa.select(table.c[column], sa.func.count()).group_by(
                        table.c[column]
                    )
                )
                .tuples()
                .all()
            )

        def queue(table: sa.Table) -> dict[str, Any]:
            waiting = table.c.state.in_(("pending", "retry_wait"))
            row = (
                connection.execute(
                    sa.select(
                        sa.func.count()
                        .filter(
                            sa.and_(waiting, table.c.next_attempt_at <= sa.func.now())
                        )
                        .label("due"),
                        sa.func.min(table.c.created_at).filter(waiting).label("oldest"),
                    )
                )
                .mappings()
                .one()
            )
            return {
                "states": groups(table, "state"),
                "due": row["due"],
                "oldest_waiting_at": row["oldest"].isoformat()
                if row["oldest"]
                else None,
            }

        return {
            "schema_version": 1,
            "checked_at": datetime.now(UTC).isoformat(),
            "database": "ok",
            "migration_head": connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one(),
            "timezone": connection.execute(sa.text("SHOW timezone")).scalar_one(),
            "sources_enabled": connection.execute(
                sa.select(sa.func.count())
                .select_from(ingestion_source)
                .where(ingestion_source.c.enabled.is_(True))
            ).scalar_one(),
            "imports": {
                "states": groups(ingestion_imports, "state"),
                "archives": groups(ingestion_imports, "archive_state"),
            },
            "pod": queue(shipment_images),
            "exports": queue(jobs),
            "ingestion_errors_by_code": groups(ingestion_errors, "reason_code"),
        }


def main() -> int:
    engine = create_database_engine(DatabaseSettings())
    try:
        print(json.dumps(diagnose(engine)))
        return 0
    except SQLAlchemyError:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "database": "unavailable",
                    "message": "Diagnostics unavailable; check database/schema",
                }
            )
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
