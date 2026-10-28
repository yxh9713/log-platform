"""PostgreSQL acceptance/status; Redis is not the export source of truth."""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Engine

from app.auth.dto import Principal
from app.exports.dto import ExportList, ExportStatus
from app.exports.schema import jobs
from app.shipments.common import DomainError, shipper_scope
from app.shipments.queries import filtered_population, reporting_day
from app.shipments.query_dto import TrackingQuery

MAX_OUTSTANDING = 50


def status(row: sa.RowMapping) -> ExportStatus:
    return ExportStatus(
        id=row["id"],
        state=row["state"],
        created_at=row["created_at"],
        url=f"/v1/exports/{row['id']}/download" if row["state"] == "ready" else None,
        row_count=row["row_count"],
        reason_code=row["reason_code"],
    )


def owned(principal: Principal) -> sa.ColumnElement[bool]:
    return sa.and_(
        jobs.c.company_id == int(principal.company.id),
        jobs.c.requester_id == int(principal.id),
    )


class ExportService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def accept(self, principal: Principal, query: TrackingQuery) -> str:
        with self.engine.begin() as connection:
            tenant = shipper_scope(connection, principal)
            # Serialize the bounded requester queue without restricting other users.
            connection.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"exports:{tenant}:{principal.id}"},
            )
            total = connection.execute(
                sa.select(sa.func.count())
                .select_from(jobs)
                .where(owned(principal), jobs.c.dismissed_at.is_(None))
            ).scalar_one()
            if total >= MAX_OUTSTANDING:
                raise DomainError(
                    429, "Dismiss completed exports before requesting more"
                )
            today = reporting_day(connection)
            normalized = query.model_copy(
                update={
                    "start_date": query.start_date or today,
                    "end_date": query.end_date or today,
                    "page": 1,
                    "length": 10,
                    "export": 0,
                }
            )
            # Validate active area ownership without executing the package query.
            filtered_population(connection, tenant, normalized)
            identity = str(uuid4())
            connection.execute(
                jobs.insert().values(
                    id=identity,
                    company_id=tenant,
                    requester_id=int(principal.id),
                    filters=normalized.model_dump(mode="json"),
                )
            )
            return identity

    def list(self, principal: Principal) -> ExportList:
        with self.engine.begin() as connection:
            shipper_scope(connection, principal)
            rows = connection.execute(
                sa.select(jobs)
                .where(owned(principal), jobs.c.dismissed_at.is_(None))
                .order_by(jobs.c.created_at, jobs.c.id)
                .limit(MAX_OUTSTANDING)
            ).mappings()
            return ExportList(items=[status(row) for row in rows])

    def get(self, principal: Principal, identity: str) -> sa.RowMapping:
        with self.engine.begin() as connection:
            shipper_scope(connection, principal)
            row = (
                connection.execute(
                    sa.select(jobs).where(owned(principal), jobs.c.id == identity)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise DomainError(404, "Export not found")
            return row

    def dismiss(self, principal: Principal, identity: str) -> None:
        with self.engine.begin() as connection:
            shipper_scope(connection, principal)
            row = connection.execute(
                sa.select(jobs.c.state)
                .where(owned(principal), jobs.c.id == identity)
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise DomainError(404, "Export not found")
            if row not in ("ready", "failed"):
                raise DomainError(409, "Export is still processing")
            connection.execute(
                jobs.update()
                .where(jobs.c.id == identity)
                .values(dismissed_at=sa.func.now(), updated_at=sa.func.now())
            )
