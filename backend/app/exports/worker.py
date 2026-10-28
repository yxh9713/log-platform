"""Streaming CSV generation with bounded attempts and crash-safe publication."""

import csv
import hashlib
import os
import tempfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dto import CompanyIdentity, Principal
from app.db.schema import company, user_role, users
from app.exports.schema import jobs
from app.exports.storage import artifact
from app.ingestion.worker import now
from app.shipments.common import DomainError
from app.shipments.queries import QueryService, filtered_population, reporting_day
from app.shipments.query_dto import TrackingQuery
from app.shipments.time_rules import display_instant

COLUMNS = (
    "shipment_number",
    "carrier",
    "route",
    "order_date",
    "due_date",
    "pod_name",
    "deliver_time",
)
DELAYS = (5, 30, 120, 600, 1800)
MAX_BYTES = 250_000_000


class ExportTooLarge(Exception):
    pass


def csv_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    # Prefix formulas, including those hidden after whitespace/control characters.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + text
    return text


class ExportWorker:
    def __init__(
        self, engine: Engine, root: Path, heartbeat: Callable[[], None] = lambda: None
    ):
        self.engine, self.root, self.heartbeat = engine, root, heartbeat

    def tick(self) -> None:
        with self.engine.connect() as connection:
            ids = list(
                connection.execute(
                    sa.select(jobs.c.id)
                    .where(
                        jobs.c.state.in_(("pending", "retry_wait")),
                        jobs.c.next_attempt_at <= sa.func.clock_timestamp(),
                    )
                    .order_by(jobs.c.next_attempt_at, jobs.c.id)
                    .limit(20)
                ).scalars()
            )
        for identity in ids:
            self.run_job(str(identity))
            self.heartbeat()
        self.heartbeat()

    def run_job(self, identity: str) -> None:
        with self.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as lock:
            key = "export:" + identity
            if not lock.execute(
                sa.text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                {"key": key},
            ).scalar_one():
                return
            try:
                self._run(identity)
            finally:
                try:
                    lock.execute(
                        sa.text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                        {"key": key},
                    )
                except SQLAlchemyError:
                    lock.invalidate()

    def _run(self, identity: str) -> None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(jobs).where(jobs.c.id == identity).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["state"] in ("ready", "failed")
                or row["next_attempt_at"] > now(connection)
            ):
                return
            if row["attempts"] >= 5:
                connection.execute(
                    jobs.update()
                    .where(jobs.c.id == identity)
                    .values(
                        state="failed",
                        reason_code="export_exhausted",
                        updated_at=sa.func.now(),
                    )
                )
                return
            attempt = row["attempts"] + 1
            connection.execute(
                jobs.update()
                .where(jobs.c.id == identity)
                .values(
                    state="retry_wait",
                    attempts=attempt,
                    reason_code=None,
                    next_attempt_at=now(connection)
                    + timedelta(seconds=DELAYS[attempt - 1]),
                    updated_at=sa.func.now(),
                )
            )
        try:
            filename, count, size, checksum = self.generate(row)
        except (
            OSError,
            SQLAlchemyError,
            DomainError,
            ValueError,
            ExportTooLarge,
        ) as error:
            terminal = (
                isinstance(error, (DomainError, ValueError, ExportTooLarge))
                or attempt >= 5
            )
            reason = (
                "export_unauthorized"
                if isinstance(error, DomainError)
                else "export_too_large"
                if isinstance(error, ExportTooLarge)
                else "export_exhausted"
                if attempt >= 5
                else "export_unavailable"
            )
            with self.engine.begin() as connection:
                connection.execute(
                    jobs.update()
                    .where(jobs.c.id == identity)
                    .values(
                        state="failed" if terminal else "retry_wait",
                        reason_code=reason,
                        updated_at=sa.func.now(),
                    )
                )
            return
        # Publication precedes readiness; crashes retry only nonready jobs.
        with self.engine.begin() as connection:
            connection.execute(
                jobs.update()
                .where(jobs.c.id == identity)
                .values(
                    state="ready",
                    filename=filename,
                    row_count=count,
                    size_bytes=size,
                    content_hash=checksum,
                    reason_code=None,
                    updated_at=sa.func.now(),
                )
            )

    def generate(self, job: sa.RowMapping) -> tuple[str, int, int, str]:
        with self.engine.connect() as connection:
            member = (
                connection.execute(
                    sa.select(
                        users.c.id,
                        users.c.email,
                        company.c.id.label("company_id"),
                        company.c.name,
                        company.c.slug,
                        user_role.c.name.label("role"),
                    )
                    .select_from(users.join(company).join(user_role))
                    .where(
                        users.c.id == job["requester_id"],
                        users.c.company_id == job["company_id"],
                        users.c.active.is_(True),
                        company.c.active.is_(True),
                        company.c.company_type == 2,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if member is None:
                raise DomainError(401, "Authentication required")
        principal = Principal(
            id=str(member["id"]),
            email=member["email"],
            role=member["role"],
            company=CompanyIdentity(
                id=str(member["company_id"]), name=member["name"], slug=member["slug"]
            ),
            expires_at=job["created_at"],
        )
        query = TrackingQuery.model_validate(job["filters"])
        temporary: str | None = None
        try:
            with QueryService(self.engine).snapshot(principal) as (connection, tenant):
                filename = f"shipment-{reporting_day(connection).isoformat()}.csv"
                final = artifact(self.root, str(job["id"]), filename)
                final.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
                base = filtered_population(
                    connection, tenant, query, validate_areas=False
                )
                c = base.c
                # Stable package order; preferences do not change the population.
                statement = sa.select(
                    c.shipment_number,
                    c.carrier,
                    c.route_name,
                    c.order_date,
                    c.due_date,
                    c.pod_name,
                    c.deliver_time,
                    c.timezone,
                ).order_by(c.id)
                count = 0
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    dir=final.parent,
                    prefix=".part-",
                    delete=False,
                ) as output:
                    temporary = output.name
                    writer = csv.writer(output)
                    writer.writerow(COLUMNS)
                    with connection.execution_options(yield_per=500).execute(
                        statement
                    ) as rows:
                        for row in rows.mappings():
                            delivery = (
                                display_instant(
                                    row["deliver_time"], row["timezone"]
                                ).isoformat()
                                if row["deliver_time"] is not None
                                else None
                            )
                            writer.writerow(
                                [
                                    csv_cell(row[key])
                                    for key in (
                                        "shipment_number",
                                        "carrier",
                                        "route_name",
                                        "order_date",
                                        "due_date",
                                        "pod_name",
                                    )
                                ]
                                + [csv_cell(delivery)]
                            )
                            count += 1
                            if count % 500 == 0:
                                output.flush()
                                self.heartbeat()
                                if output.tell() > MAX_BYTES:
                                    raise ExportTooLarge()
                    output.flush()
                    os.fsync(output.fileno())
                size = Path(temporary).stat().st_size
                if size > MAX_BYTES:
                    raise ExportTooLarge()
                digest = hashlib.sha256()
                with open(temporary, "rb") as content:
                    while data := content.read(65536):
                        digest.update(data)
                # Workers share a trusted private root/group; API mounts it read-only.
                os.chmod(temporary, 0o640)
                if final.is_symlink():
                    raise ValueError("Invalid artifact path")
                os.replace(temporary, final)
                temporary = None
                directory = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                return filename, count, size, digest.hexdigest()
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
