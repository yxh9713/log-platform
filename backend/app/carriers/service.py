"""Shared carrier event transaction; webhook receipt and CSV checkpoint own commits."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.dialects.postgresql import insert

from app.carriers.schema import carrier_receipts, integrations
from app.db.schema import company, shipment_actions
from app.ingestion.schema import shipment_field_receipts
from app.ingestion.shipments import apply_fields
from app.integrations.carriers.ontrac.transformer import WEBHOOK_EVENTS, transform
from app.integrations.shippers.paychex.transformer import source_time
from app.pod.prepare import prepare
from app.pod.service import enqueue
from app.shipments.accounts import AccountMappingService
from app.shipments.areas import AreaService
from app.shipments.common import DomainError, lock_tenant
from app.shipments.schema import (
    area,
    ingestion_errors,
    receipt_order,
    shipment_events,
    shipments,
)
from app.shipments.service import recipient_zone
from app.shipments.time_rules import normalize_instant


@dataclass(frozen=True)
class EventResult:
    outcome: Literal["accepted", "duplicate", "ignored", "rejected"]
    shipment_id: int | None = None
    event_id: int | None = None


class CarrierFailure(DomainError):
    def __init__(self, error: DomainError, tenant: int | None = None):
        super().__init__(error.status, error.message, error.code)
        self.tenant = tenant


def process_event(
    connection: Connection,
    carrier: int,
    values: dict[str, Any],
    receipt: int,
    *,
    csv: bool = False,
) -> EventResult:
    tenant: int | None = None
    try:
        payload = transform(values, csv=csv)
        if payload is None:
            return EventResult("ignored")
        tenant = AccountMappingService.resolve_shipper(
            connection, carrier, payload.account
        )
        lock_tenant(connection, tenant)
        row = (
            connection.execute(
                sa.select(shipments).where(
                    shipments.c.shipper_company_id == tenant,
                    shipments.c.carrier_company_id == carrier,
                    shipments.c.account_id == payload.account,
                    shipments.c.shipper_ref == payload.reference,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DomainError(400, "Shipment not found", "unmatched_shipment")
        action = connection.execute(
            sa.select(shipment_actions.c.id).where(
                shipment_actions.c.action == WEBHOOK_EVENTS[payload.event]
            )
        ).scalar_one_or_none()
        if action is None:
            raise DomainError(
                503, "Carrier catalog is not configured", "missing_catalog"
            )
        # An accepted raw timestamp keeps its original normalization even if an
        # address-validation job subsequently changes the recipient timezone.
        prior = connection.execute(
            sa.select(shipment_events.c.id)
            .where(
                shipment_events.c.shipment_id == row["id"],
                shipment_events.c.action_id == action,
                shipment_events.c.source_time == payload.time,
            )
            .limit(1)
        ).scalar_one_or_none()
        if prior is not None:
            return EventResult("duplicate", row["id"], prior)
        zone = recipient_zone(connection, row["recipient_id"], tenant)
        event_time = normalize_instant(payload.time, zone)
        prior = connection.execute(
            sa.select(shipment_events.c.id).where(
                shipment_events.c.shipment_id == row["id"],
                shipment_events.c.action_id == action,
                shipment_events.c.event_time == event_time,
            )
        ).scalar_one_or_none()
        if prior is not None:
            return EventResult("duplicate", row["id"], prior)
        deadline = source_time(payload.due_time)
        due = normalize_instant(deadline, zone) if deadline else None
        route_name = AreaService.validate_name(payload.route) if payload.route else None
        image = prepare(payload.pod) if payload.pod else None
        event_id = connection.execute(
            insert(shipment_events)
            .values(
                shipment_id=row["id"],
                action_id=action,
                event_time=event_time,
                receipt_order=receipt,
                source_time=payload.time,
                normalization_zone=zone,
            )
            .on_conflict_do_nothing(constraint="uq_shipment_events_exact")
            .returning(shipment_events.c.id)
        ).scalar_one_or_none()
        if event_id is None:
            return EventResult("duplicate", row["id"])
        if image is not None:
            enqueue(connection, tenant, row["id"], int(event_id), image)
        route = None
        if route_name:
            old_receipt = connection.execute(
                sa.select(shipment_field_receipts.c.receipt_order).where(
                    shipment_field_receipts.c.shipment_id == row["id"],
                    shipment_field_receipts.c.field_name == "route",
                )
            ).scalar_one_or_none()
            if old_receipt is None or old_receipt < receipt:
                connection.execute(
                    insert(area)
                    .values(company_id=tenant, name=route_name)
                    .on_conflict_do_nothing(constraint="uq_area_company_name")
                )
                route = connection.execute(
                    sa.select(area.c.id).where(
                        area.c.company_id == tenant,
                        area.c.name == route_name,
                    )
                ).scalar_one()
        apply_fields(
            connection,
            row["id"],
            {
                "shipment_number": payload.shipment_number,
                "notes": payload.notes,
                "due_time": due,
                "pod_name": payload.sign,
                "route": route,
            },
            receipt,
        )
        # Keep the most recent actual delivery even during a Returned outcome.
        # Queries reduce terminal events independently; attempts never supply time.
        delivery = connection.execute(
            sa.select(shipment_events.c.event_time)
            .join(shipment_actions)
            .where(
                shipment_events.c.shipment_id == row["id"],
                shipment_actions.c.action == "delivered",
            )
            .order_by(
                shipment_events.c.event_time.desc(),
                shipment_events.c.receipt_order.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        if delivery is not None:
            connection.execute(
                shipments.update()
                .where(shipments.c.id == row["id"])
                .values(deliver_time=delivery, updated_at=sa.func.now())
            )
        return EventResult("accepted", row["id"], int(event_id))
    except DomainError as error:
        raise CarrierFailure(error, tenant) from None


def safe_identifier(values: dict[str, Any], name: str) -> str | None:
    value = values.get(name)
    return value.strip() if isinstance(value, str) and len(value) <= 255 else None


class CarrierService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def authenticate_on(connection: Connection, raw_id: str, key: str | None) -> int:
        valid_id = (
            bool(re.fullmatch(r"[0-9]{1,19}", raw_id))
            and 0 < int(raw_id) <= 9223372036854775807
        )
        row = (
            connection.execute(
                sa.select(integrations)
                .join(company)
                .where(
                    integrations.c.id == int(raw_id),
                    integrations.c.active.is_(True),
                    integrations.c.adapter == "ontrac",
                    company.c.active.is_(True),
                    company.c.company_type == 1,
                )
                .with_for_update(read=True, of=integrations)
            )
            .mappings()
            .one_or_none()
            if valid_id
            else None
        )
        digest = hashlib.sha256((key or "").encode()).hexdigest()
        if (
            row is None
            or not key
            or len(key) > 1024
            or not hmac.compare_digest(digest, row["apikey"])
        ):
            raise DomainError(401, "Invalid API key", "invalid_api_key")
        return int(row["company_id"])

    def authenticate(self, raw_id: str, key: str | None) -> None:
        with self.engine.begin() as connection:
            self.authenticate_on(connection, raw_id, key)

    def receive(
        self, raw_id: str, key: str | None, values: dict[str, Any]
    ) -> tuple[str, EventResult, DomainError | None]:
        with self.engine.begin() as connection:
            carrier = self.authenticate_on(connection, raw_id, key)
            receipt = connection.execute(
                sa.select(receipt_order.next_value())
            ).scalar_one()
            receipt_id = str(uuid4())
            received_at = connection.execute(
                sa.select(sa.func.clock_timestamp())
            ).scalar_one()
            error: DomainError | None = None
            tenant = None
            try:
                with connection.begin_nested():
                    result = process_event(connection, carrier, values, receipt)
                    if result.shipment_id:
                        tenant = connection.execute(
                            sa.select(shipments.c.shipper_company_id).where(
                                shipments.c.id == result.shipment_id
                            )
                        ).scalar_one()
            except CarrierFailure as failure:
                # A retryable infrastructure/catalog failure is not durably
                # acknowledged as successful business processing.
                if failure.status >= 500:
                    raise
                error, tenant = failure, failure.tenant
                result = EventResult("rejected")
            connection.execute(
                carrier_receipts.insert().values(
                    id=receipt_id,
                    received_at=received_at,
                    integration_id=int(raw_id),
                    carrier_company_id=carrier,
                    shipper_company_id=tenant,
                    shipment_id=result.shipment_id,
                    event_id=result.event_id,
                    receipt_order=receipt,
                    request_hash=hashlib.sha256(
                        json.dumps(
                            values, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                    outcome=result.outcome,
                    reason_code=error.code if error else None,
                )
            )
            if error:
                connection.execute(
                    ingestion_errors.insert().values(
                        shipper_company_id=tenant,
                        carrier_company_id=carrier,
                        integration_id=int(raw_id),
                        carrier_receipt_id=receipt_id,
                        source_type="carrier_webhook",
                        reason_code=error.code,
                        received_reference=safe_identifier(values, "reference"),
                        received_account=safe_identifier(values, "account"),
                    )
                )
            return receipt_id, result, error
