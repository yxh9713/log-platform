"""Measured PostgreSQL baseline in an automatically dropped synthetic database."""

import argparse
import json
import math
import os
import platform
import resource
import statistics
import tempfile
import time
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from alembic import command
from app.auth.dto import CompanyIdentity, Principal
from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.db.schema import company, shipment_actions, user_role, users
from app.db.seed import seed_database
from app.exports.service import ExportService
from app.exports.worker import ExportWorker
from app.shipments.accounts import AccountMappingService
from app.shipments.areas import AreaService
from app.shipments.day import DayService
from app.shipments.dto import AreaInput
from app.shipments.queries import QueryService, filtered_population, reporting_day
from app.shipments.query_dto import SearchQuery, TrackingQuery
from app.shipments.schema import shipment_events, shipments
from app.shipments.service import ShipmentService
from tests.shipment_support import shipment_input


def fixture(engine: sa.Engine, count: int) -> tuple[Principal, int, int]:
    seed_database(engine)
    with engine.begin() as c:
        primary = c.execute(
            sa.select(company.c.id).where(company.c.slug == "paychex")
        ).scalar_one()
        carrier = c.execute(
            sa.select(company.c.id).where(company.c.slug == "ontrac")
        ).scalar_one()
        administrator = c.execute(
            sa.select(users.c.id, users.c.email)
            .join(user_role)
            .where(user_role.c.name == "administrator")
        ).one()
        other = c.execute(
            company.insert()
            .values(
                name="Synthetic benchmark tenant",
                slug="benchmark-other",
                company_type=2,
            )
            .returning(company.c.id)
        ).scalar_one()
        role = c.execute(
            sa.select(user_role.c.id).where(user_role.c.name == "administrator")
        ).scalar_one()
        other_user = c.execute(
            users.insert()
            .values(
                company_id=other,
                role_id=role,
                email="benchmark@example.test",
                password="synthetic-unused-not-a-login-hash",
            )
            .returning(users.c.id)
        ).scalar_one()
        day = reporting_day(c)
        actions = dict(
            c.execute(sa.select(shipment_actions.c.action, shipment_actions.c.id))
            .tuples()
            .all()
        )
    principal = Principal(
        id=str(administrator.id),
        email=administrator.email,
        role="administrator",
        company=CompanyIdentity(id=str(primary), name="Paychex", slug="paychex"),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    first_id = 0
    selected_area = 0
    for tenant, user, account, amount in (
        (primary, int(principal.id), "0007", count * 4 // 5),
        (other, other_user, "0008", count - count * 4 // 5),
    ):
        identity = principal.model_copy(
            update={
                "id": str(user),
                "company": CompanyIdentity(
                    id=str(tenant), name="Synthetic", slug="synthetic"
                ),
            }
        )
        AccountMappingService(engine).configure(
            tenant, carrier, "TEST.SERVICE", account
        )
        areas = [
            AreaService(engine).create(identity, AreaInput(name=f"zone-{i}"))[0].id
            for i in range(10)
        ]
        AreaService(engine).delete(identity, areas[-1])
        master = int(
            ShipmentService(engine)
            .create(
                identity,
                shipment_input(
                    reference="B000000",
                    account_number=account,
                    shipment_number="DUP-000",
                    due_time=datetime.combine(day, day_time(17), UTC).isoformat(),
                ),
            )
            .shipment.id
        )
        if tenant == primary:
            first_id = master
            selected_area = areas[0]
        with engine.begin() as c:
            source = dict(
                c.execute(sa.select(shipments).where(shipments.c.id == master))
                .mappings()
                .one()
            )
            source.pop("id")
            c.execute(
                shipment_events.delete().where(shipment_events.c.shipment_id == master)
            )
            for start in range(0, amount, 500):
                values = []
                for index in range(start, min(start + 500, amount)):
                    item = {
                        **source,
                        "shipper_ref": f"B{index:06}",
                        "shipment_number": f"DUP-{index % 100:03}",
                        "route": areas[index % 10],
                        "order_date": day - timedelta(days=index % 7),
                        "deleted_at": datetime.combine(day, day_time(8), UTC)
                        if index % 50 == 0
                        else None,
                        "deliver_time": datetime.combine(day, day_time(13), UTC)
                        if index % 4 < 2
                        else None,
                        "pod_name": "Synthetic signer" if index % 4 < 2 else None,
                    }
                    if index == 0:
                        c.execute(
                            shipments.update()
                            .where(shipments.c.id == master)
                            .values(**item)
                        )
                    else:
                        values.append(item)
                if values:
                    c.execute(shipments.insert(), values)
            records = c.execute(
                sa.select(shipments.c.id, shipments.c.shipper_ref).where(
                    shipments.c.shipper_company_id == tenant
                )
            ).all()
            for start in range(0, len(records), 100):
                events = []
                for row in records[start : start + 100]:
                    index = int(row.shipper_ref[1:])
                    terminal = ("delivered", "returned", "attempted", "possession")[
                        index % 4
                    ]
                    for hour, action in enumerate(
                        (
                            "created",
                            "picked up",
                            "possession",
                            "out for delivery",
                            terminal,
                        ),
                        9,
                    ):
                        events.append(
                            {
                                "shipment_id": row.id,
                                "action_id": actions[action],
                                "event_time": datetime.combine(
                                    day, day_time(hour), UTC
                                ),
                            }
                        )
                c.execute(shipment_events.insert(), events)
    with engine.begin() as c:
        c.execute(sa.text("ANALYZE"))
    return principal, first_id, selected_area


def measure(engine: sa.Engine, operation: Any, samples: int) -> dict[str, Any]:
    statements = 0

    def executed(*args: Any) -> None:
        nonlocal statements
        statements += 1

    for _ in range(2):
        operation()
    durations = []
    queries = []
    sa.event.listen(engine, "before_cursor_execute", executed)
    try:
        for _ in range(samples):
            statements = 0
            start = time.perf_counter()
            operation()
            durations.append((time.perf_counter() - start) * 1000)
            queries.append(statements)
    finally:
        sa.event.remove(engine, "before_cursor_execute", executed)
    ordered = sorted(durations)
    return {
        "samples": samples,
        "median_ms": round(statistics.median(durations), 3),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3),
        "min_ms": round(min(durations), 3),
        "max_ms": round(max(durations), 3),
        "sql_statements_min": min(queries),
        "sql_statements_max": max(queries),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=int, default=10000)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/p12-performance.json")
    )
    args = parser.parse_args()
    if not 1000 <= args.packages <= 100000 or not 3 <= args.samples <= 30:
        raise ValueError("Invalid bounded benchmark parameters")
    config = DatabaseSettings()
    if config.app_env != "test":
        raise RuntimeError("Performance fixtures require APP_ENV=test")
    parent = str(config.database_url)
    with psycopg.connect(parent, autocommit=True) as c:
        current = c.execute("SELECT current_database()").fetchone()
        if current is None or current[0] != "logistics_p12":
            raise RuntimeError("Performance fixtures require the isolated P12 database")
    name = "p12_perf_" + uuid4().hex
    with psycopg.connect(parent, autocommit=True) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                sql.Identifier(name)
            )
        )
    os.environ["DATABASE_URL"] = (
        make_url(parent).set(database=name).render_as_string(hide_password=False)
    )
    engine = create_database_engine(DatabaseSettings())
    try:
        command.upgrade(Config("alembic.ini"), "head")
        principal, identity, area = fixture(engine, args.packages)
        service = QueryService(engine)
        results = {
            "tracking_today": measure(
                engine,
                lambda: service.tracking(principal, TrackingQuery()),
                args.samples,
            ),
            "tracking_account_area_undelivered": measure(
                engine,
                lambda: service.tracking(
                    principal,
                    TrackingQuery(account="0007", area=[area], status="undelivered"),
                ),
                args.samples,
            ),
            "my_day": measure(
                engine, lambda: DayService(engine).my_day(principal), args.samples
            ),
            "search_duplicate_number": measure(
                engine,
                lambda: service.search(
                    principal,
                    SearchQuery(identifier="DUP-001", field="shipment_number"),
                ),
                args.samples,
            ),
            "detail": measure(
                engine, lambda: service.detail(principal, identity), args.samples
            ),
        }
        exports = ExportService(engine)
        with tempfile.TemporaryDirectory() as root:
            job = exports.accept(principal, TrackingQuery())
            start = time.perf_counter()
            ExportWorker(engine, Path(root)).run_job(job)
            output = exports.get(principal, job)
            assert (
                output["state"] == "ready"
                and output["row_count"] == args.packages * 4 // 5
            )
            results["export"] = {
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                "rows": output["row_count"],
                "bytes": output["size_bytes"],
            }
        with engine.connect() as c:
            filtered = filtered_population(
                c, int(principal.company.id), TrackingQuery()
            )
            statement = (
                sa.select(filtered)
                .order_by(filtered.c.due_time, filtered.c.id)
                .limit(10)
            )
            compiled = statement.compile(
                dialect=engine.dialect, compile_kwargs={"literal_binds": True}
            )
            plan = c.execute(
                sa.text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(compiled))
            ).scalar_one()[0]
            version = c.execute(sa.text("SHOW server_version")).scalar_one()
            actual_events = c.execute(
                sa.select(sa.func.count()).select_from(shipment_events)
            ).scalar_one()
        report = {
            "schema_version": 1,
            "fixture": {
                "packages": args.packages,
                "events": actual_events,
                "tenants": 2,
                "primary_packages": args.packages * 4 // 5,
                "areas_per_tenant": 10,
                "deleted_areas_per_tenant": 1,
                "recipient_timezones": "UTC fallback",
            },
            "environment": {
                "postgres": version,
                "architecture": platform.machine(),
                "visible_cpus": os.cpu_count(),
                "warmups": 2,
                "concurrency": 1,
                "process_peak_rss_kib": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss,
            },
            "results": results,
            "tracking_page_explain": plan,
            "limitations": [
                "Local warm single-client baseline; no production capacity/SLO claim",
                "RSS includes fixtures/interpreter; excludes PostgreSQL",
                "Shared synthetic recipients; real data/hardware may differ",
            ],
        }
        args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(json.dumps({"performance_report": str(args.output), "results": results}))
    finally:
        engine.dispose()
        with psycopg.connect(parent, autocommit=True) as c:
            c.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


if __name__ == "__main__":
    main()
