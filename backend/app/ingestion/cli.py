"""Trusted operator CLI; no public ingestion/configuration HTTP endpoint."""

import argparse
import json
import os
import re
import time
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.db.schema import company
from app.ingestion.schema import ingestion_imports as imports
from app.ingestion.schema import ingestion_source as sources
from app.ingestion.worker import IntakeWorker
from app.shipments.common import DomainError


def configure(
    engine: sa.Engine,
    slug: str,
    interval: int = 60,
    enabled: bool = True,
    adapter: str = "paychex_manifest",
) -> int:
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", slug)
        or not 1 <= interval <= 86400
        or adapter not in ("paychex_manifest", "ontrac_csv")
    ):
        raise DomainError(400, "Invalid source configuration")
    with engine.begin() as connection:
        company_id = connection.execute(
            sa.select(company.c.id).where(
                company.c.slug == slug,
                company.c.company_type == (1 if adapter == "ontrac_csv" else 2),
                company.c.active.is_(True),
            )
        ).scalar_one_or_none()
        if company_id is None:
            raise DomainError(400, "An active company of the adapter type is required")
        source_id = connection.execute(
            insert(sources)
            .values(
                company_id=company_id,
                folder=slug,
                adapter=adapter,
                poll_interval_seconds=interval,
                enabled=enabled,
            )
            .on_conflict_do_update(
                index_elements=["company_id"],
                set_={
                    "poll_interval_seconds": interval,
                    "enabled": enabled,
                    "next_poll_at": sa.func.now(),
                },
            )
            .returning(sources.c.id)
        ).scalar_one()
        return int(source_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("configure")
    source.add_argument("--company-slug", required=True)
    source.add_argument("--poll-seconds", type=int, default=60)
    source.add_argument("--disabled", action="store_true")
    source.add_argument(
        "--adapter",
        choices=("paychex_manifest", "ontrac_csv"),
        default="paychex_manifest",
    )
    for name in ("once", "run"):
        command = commands.add_parser(name)
        command.add_argument(
            "--root",
            type=Path,
            default=Path(os.environ.get("INGESTION_ROOT", "/data/sftp")),
        )
    commands.add_parser("status")
    retry = commands.add_parser("retry-archive")
    retry.add_argument("--import-id", required=True)
    args = parser.parse_args()
    engine = create_database_engine(DatabaseSettings())
    try:
        if args.command == "configure":
            source_id = configure(
                engine,
                args.company_slug,
                args.poll_seconds,
                not args.disabled,
                args.adapter,
            )
            print(json.dumps({"source_id": str(source_id), "configured": True}))
        elif args.command == "status":
            with engine.connect() as connection:
                result = (
                    connection.execute(
                        sa.select(
                            imports.c.id,
                            imports.c.source_id,
                            imports.c.state,
                            imports.c.rows_total,
                            imports.c.rows_completed,
                            imports.c.rows_rejected,
                            imports.c.rows_ignored,
                            imports.c.rows_duplicate,
                            imports.c.attempts,
                            imports.c.archive_state,
                            imports.c.archive_attempts,
                            imports.c.reason_code,
                        )
                        .order_by(imports.c.received_at.desc())
                        .limit(100)
                    )
                    .mappings()
                    .all()
                )
                print(json.dumps([dict(row) for row in result], default=str))
        elif args.command == "retry-archive":
            with engine.begin() as connection:
                changed = connection.execute(
                    imports.update()
                    .where(
                        imports.c.id == args.import_id,
                        imports.c.archive_state == "exhausted",
                    )
                    .values(
                        archive_state="pending",
                        archive_attempts=0,
                        archive_next_at=sa.func.now(),
                    )
                    .returning(imports.c.id)
                ).scalar_one_or_none()
                print(json.dumps({"archive_retry_scheduled": changed is not None}))
        else:
            heartbeat = Path("/tmp/intake-heartbeat")
            worker = IntakeWorker(engine, args.root, heartbeat.touch)
            if args.command == "once":
                worker.tick(force=True)
                print(json.dumps({"scan_completed": True}))
            else:
                while True:
                    try:
                        worker.tick()
                    except (SQLAlchemyError, OSError, DomainError):
                        # No DSN, credential, filename or row data in logs.
                        print(
                            json.dumps(
                                {
                                    "worker": "intake",
                                    "outcome": "infrastructure_or_source_unavailable",
                                }
                            ),
                            flush=True,
                        )
                    time.sleep(1)
    except (SQLAlchemyError, OSError, DomainError, ValueError):
        print(
            json.dumps(
                {"error": "Intake failed; inspect configuration and import status"}
            )
        )
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
