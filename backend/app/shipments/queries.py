"""Tenant-scoped reads. Event reduction produces one row per package before paging."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.sql import ColumnElement

from app.auth.dto import Principal
from app.db.schema import company, shipment_actions
from app.pod.service import current_url
from app.shipments.common import DomainError, shipper_scope
from app.shipments.query_dto import (
    Address,
    HistoryEvent,
    Metrics,
    SearchQuery,
    SearchResult,
    SearchRow,
    ShipmentDetail,
    TrackingQuery,
    TrackingResult,
    TrackingRow,
)
from app.shipments.schema import (
    area,
    customers,
    customers_validated,
    shipment_events,
    shipments,
)
from app.shipments.time_rules import display_instant


def latest_action(terminal: bool = False) -> ColumnElement[Any]:
    query = (
        sa.select(shipment_actions.c.action)
        .select_from(shipment_events.join(shipment_actions))
        .where(shipment_events.c.shipment_id == shipments.c.id)
    )
    if terminal:
        query = query.where(shipment_actions.c.action.in_(("delivered", "returned")))
    return (
        query.order_by(
            shipment_events.c.event_time.desc(), shipment_events.c.receipt_order.desc()
        )
        .limit(1)
        .correlate(shipments)
        .scalar_subquery()
    )


def population(tenant: int) -> sa.Subquery:
    recipient = customers.alias("recipient")
    status = sa.case(
        (shipments.c.deleted_at.is_not(None), "Void"),
        (latest_action(True) == "returned", "Undelivered"),
        (
            sa.and_(
                shipments.c.deliver_time.is_not(None),
                sa.func.length(sa.func.btrim(shipments.c.pod_name)) > 0,
            ),
            "Delivered",
        ),
        else_="Undelivered",
    )
    return (
        sa.select(
            shipments,
            company.c.name.label("carrier"),
            area.c.name.label("route_name"),
            customers_validated.c.timezone,
            *[
                recipient.c[name].label(f"recipient_{name}")
                for name in (
                    "company",
                    "address_one",
                    "address_two",
                    "city",
                    "state",
                    "zip",
                )
            ],
            status.label("current_status"),
            latest_action().label("latest_action"),
        )
        .select_from(
            shipments.join(company, company.c.id == shipments.c.carrier_company_id)
            .join(
                recipient,
                sa.and_(
                    recipient.c.id == shipments.c.recipient_id,
                    recipient.c.company_id == tenant,
                ),
            )
            .outerjoin(
                customers_validated,
                sa.and_(
                    customers_validated.c.id == recipient.c.validated_id,
                    customers_validated.c.company_id == tenant,
                ),
            )
            .outerjoin(
                area,
                sa.and_(area.c.id == shipments.c.route, area.c.company_id == tenant),
            )
        )
        .where(shipments.c.shipper_company_id == tenant)
        .subquery()
    )


def tracking_row(row: sa.RowMapping) -> TrackingRow:
    def local(value: datetime | None) -> datetime | None:
        return display_instant(value, row["timezone"]) if value is not None else None

    return TrackingRow(
        id=str(row["id"]),
        shipment_number=row["shipment_number"],
        reference=row["shipper_ref"],
        reference_two=row["shipper_ref2"],
        account=row["account_id"],
        carrier=row["carrier"],
        service_name=row["service_type"],
        route_id=row["route"],
        route=row["route_name"],
        company=row["recipient_company"],
        address_one=row["recipient_address_one"],
        address_two=row["recipient_address_two"],
        city=row["recipient_city"],
        state=row["recipient_state"],
        zip=row["recipient_zip"],
        status=row["current_status"],
        pod_name=row["pod_name"],
        deliver_time=local(row["deliver_time"]),
        due_time=display_instant(row["due_time"], row["timezone"]),
        due_date=row["due_date"],
        weight=row["weight"],
    )


def metric_columns(filtered: sa.Subquery) -> list[ColumnElement[Any]]:
    c = filtered.c
    return [
        sa.func.count(c.id).label("total"),
        sa.func.count(c.id).filter(c.current_status == "Delivered").label("delivered"),
        sa.func.count(c.id)
        .filter(c.current_status == "Undelivered")
        .label("undelivered"),
        sa.func.count(c.id).filter(c.current_status == "Void").label("void"),
        sa.func.count(c.id)
        .filter(sa.and_(c.current_status == "Delivered", c.deliver_time < c.due_time))
        .label("on_time"),
    ]


def metric_result(row: sa.RowMapping) -> Metrics:
    eligible = row["total"] - row["void"]
    otp = (
        Decimal(0)
        if not eligible
        else Decimal(100)
        if not row["delivered"]
        else Decimal(100) * row["on_time"] / row["delivered"]
    )
    return Metrics(
        total=row["total"],
        delivered=row["delivered"],
        undelivered=row["undelivered"],
        void=row["void"],
        otp=float(otp.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    )


def metrics(connection: Connection, filtered: sa.Subquery) -> Metrics:
    return metric_result(
        connection.execute(sa.select(*metric_columns(filtered))).mappings().one()
    )


def reporting_day(connection: Connection) -> date:
    return connection.execute(
        sa.select(sa.cast(sa.func.timezone("UTC", sa.func.now()), sa.Date))
    ).scalar_one()


def filtered_population(
    connection: Connection,
    tenant: int,
    query: TrackingQuery,
    *,
    validate_areas: bool = True,
) -> sa.Subquery:
    today = reporting_day(connection)
    start, end = query.start_date or today, query.end_date or today
    base = population(tenant)
    c = base.c
    conditions: list[ColumnElement[bool]] = []
    column = c[query.date_type]
    if query.date_type in ("due_date", "order_date"):
        conditions.extend((column >= start, column <= end))
    else:
        conditions.append(column >= datetime.combine(start, time.min, UTC))
        # Avoid overflow for the largest valid calendar date.
        if end != date.max:
            conditions.append(
                column < datetime.combine(end + timedelta(days=1), time.min, UTC)
            )
        else:
            conditions.append(sa.cast(sa.func.timezone("UTC", column), sa.Date) <= end)
    if query.account is not None:
        conditions.append(c.account_id == query.account)
    if query.status:
        conditions.append(c.current_status == query.status.capitalize())
    if query.exception == "void":
        conditions.append(c.current_status == "Void")
    elif query.exception:
        conditions.extend(
            (
                c.current_status == "Undelivered",
                c.latest_action == query.exception,
            )
        )
    if query.area and validate_areas:
        selected = set(query.area)
        active = set(
            connection.execute(
                sa.select(area.c.id).where(
                    area.c.company_id == tenant,
                    area.c.deleted_at.is_(None),
                    area.c.id.in_(selected),
                )
            ).scalars()
        )
        if active != selected:
            raise DomainError(400, "Invalid area selection")
    if query.area:
        conditions.append(c.route.in_(set(query.area)))
    return sa.select(base).where(*conditions).subquery()


class QueryService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @contextmanager
    def snapshot(self, principal: Principal) -> Iterator[tuple[Connection, int]]:
        # Count, page, addresses and history share one committed database snapshot.
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            yield connection, shipper_scope(connection, principal)

    def tracking(self, principal: Principal, query: TrackingQuery) -> TrackingResult:
        with self.snapshot(principal) as (connection, tenant):
            today = reporting_day(connection)
            start, end = query.start_date or today, query.end_date or today
            filtered = filtered_population(connection, tenant, query)
            counts = metrics(connection, filtered)
            sort_fields = {
                "reference": "shipper_ref",
                "route": "route_name",
                "company": "recipient_company",
                "city": "recipient_city",
                "zip": "recipient_zip",
                "status": "current_status",
            }
            sort_column = filtered.c[sort_fields.get(query.sort, query.sort)]
            order = (
                sort_column.desc() if query.direction == "desc" else sort_column.asc()
            )
            rows = connection.execute(
                sa.select(filtered)
                .order_by(order.nulls_last(), filtered.c.id.asc())
                .limit(query.length)
                .offset((query.page - 1) * query.length)
            ).mappings()
            return TrackingResult(
                items=[tracking_row(row) for row in rows],
                total=counts.total,
                page=query.page,
                length=query.length,
                pages=(counts.total + query.length - 1) // query.length,
                start_date=start,
                end_date=end,
                date_type=query.date_type,
                metrics=counts,
            )

    def search(self, principal: Principal, query: SearchQuery) -> SearchResult:
        with self.snapshot(principal) as (connection, tenant):
            base = population(tenant)
            field = (
                base.c.shipper_ref
                if query.field == "reference"
                else base.c.shipment_number
            )
            match = sa.select(base).where(field == query.identifier).subquery()
            total = connection.execute(
                sa.select(sa.func.count()).select_from(match)
            ).scalar_one()
            rows = connection.execute(
                sa.select(match)
                .order_by(match.c.id)
                .limit(query.length)
                .offset((query.page - 1) * query.length)
            ).mappings()
            items = [
                SearchRow(
                    id=str(row["id"]),
                    shipment_number=row["shipment_number"],
                    reference=row["shipper_ref"],
                    route=row["route_name"],
                    address_one=row["recipient_address_one"],
                    city=row["recipient_city"],
                    state=row["recipient_state"],
                    zip=row["recipient_zip"],
                )
                for row in rows
            ]
            return SearchResult(
                identifier=query.identifier,
                field=query.field,
                items=items,
                total=total,
                page=query.page,
                length=query.length,
                pages=(total + query.length - 1) // query.length,
            )

    def detail(self, principal: Principal, shipment_id: int) -> ShipmentDetail:
        with self.snapshot(principal) as (connection, tenant):
            base = population(tenant)
            row = (
                connection.execute(sa.select(base).where(base.c.id == shipment_id))
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise DomainError(404, "Shipment not found")

            def address(customer_id: int) -> Address:
                result = (
                    connection.execute(
                        sa.select(customers).where(
                            customers.c.id == customer_id,
                            customers.c.company_id == tenant,
                        )
                    )
                    .mappings()
                    .one()
                )
                return Address(
                    name=result["company"],
                    **{
                        key: result[key]
                        for key in Address.model_fields
                        if key != "name"
                    },
                )

            events = connection.execute(
                sa.select(shipment_events, shipment_actions.c.action)
                .join(shipment_actions)
                .where(shipment_events.c.shipment_id == shipment_id)
                .order_by(
                    shipment_events.c.event_time.desc(),
                    shipment_events.c.receipt_order.desc(),
                )
            ).mappings()
            history = [
                HistoryEvent(
                    id=str(event["id"]),
                    action=event["action"],
                    receipt_order=str(event["receipt_order"]),
                    event_time=display_instant(event["event_time"], row["timezone"]),
                )
                for event in events
            ]
            return ShipmentDetail(
                pod_url=current_url(connection, tenant, shipment_id),
                **tracking_row(row).model_dump(),
                sender=address(row["sender_id"]),
                recipient=address(row["recipient_id"]),
                history=history,
                notes=row["notes"],
                order_date=row["order_date"],
                created_at=display_instant(row["created_at"], row["timezone"]),
            )
