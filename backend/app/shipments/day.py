"""Due-today global/exception/active-area aggregates from one committed snapshot."""

import sqlalchemy as sa

from app.auth.dto import Principal
from app.shipments.day_dto import AreaStats, DayReport, Exceptions
from app.shipments.queries import (
    QueryService,
    metric_columns,
    metric_result,
    metrics,
    population,
    reporting_day,
)
from app.shipments.schema import area


class DayService(QueryService):
    def my_day(self, principal: Principal) -> DayReport:
        with self.snapshot(principal) as (connection, tenant):
            today = reporting_day(connection)
            base = population(tenant)
            due = sa.select(base).where(base.c.due_date == today).subquery()
            c = due.c
            stats = metrics(connection, due)
            exceptions = (
                connection.execute(
                    sa.select(
                        sa.func.count()
                        .filter(
                            sa.and_(
                                c.current_status == "Undelivered",
                                c.latest_action == "attempted",
                            )
                        )
                        .label("attempted"),
                        sa.func.count()
                        .filter(
                            sa.and_(
                                c.current_status == "Undelivered",
                                c.latest_action == "returned",
                            )
                        )
                        .label("returned"),
                        sa.func.count()
                        .filter(c.current_status == "Void")
                        .label("void"),
                    )
                )
                .mappings()
                .one()
            )
            # Left join starts with active saved areas, retaining zero populations.
            # count(due.id), not count(*), keeps empty cards truly empty.
            cards = connection.execute(
                sa.select(area.c.id, area.c.name, *metric_columns(due))
                .select_from(area.outerjoin(due, c.route == area.c.id))
                .where(area.c.company_id == tenant, area.c.deleted_at.is_(None))
                .group_by(area.c.id, area.c.name)
                .order_by(area.c.name, area.c.id)
            ).mappings()
            return DayReport(
                report_date=today,
                stats=stats,
                exceptions=Exceptions(**exceptions),
                areas=[
                    AreaStats(
                        id=row["id"],
                        area=row["name"],
                        **metric_result(row).model_dump(),
                    )
                    for row in cards
                ],
            )
