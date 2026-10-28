import re
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.dialects.postgresql import insert

from app.auth.dto import Principal
from app.db.schema import shipment_actions
from app.ingestion.schema import shipment_field_receipts
from app.shipments.accounts import company_type, creation_assignment
from app.shipments.common import DomainError, lock_tenant, shipper_scope
from app.shipments.dto import AddressInput, ShipmentCreated, ShipmentInput
from app.shipments.schema import (
    customers,
    customers_validated,
    generated_shipment_numbers,
    ingestion_errors,
    shipment_events,
    shipments,
)
from app.shipments.time_rules import (
    default_deadline,
    display_instant,
    normalize_instant,
)


@dataclass(frozen=True)
class CreationResult:
    shipment: ShipmentCreated
    created: bool


def random_number() -> str:
    return "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(15)
    )


def number_lock(connection: Connection) -> None:
    # The matching database trigger coordinates all number writes, including
    # future carrier corrections and trusted SQL, without blanket uniqueness.
    connection.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended('shipment-numbers', 0))")
    )


def generate_number(connection: Connection, factory: Callable[[], str]) -> str:
    number_lock(connection)
    for _ in range(10):
        number = factory()
        if not re.fullmatch(r"[A-Z0-9]{12,15}", number):
            raise DomainError(
                503, "Shipment number generation failed", "number_generation"
            )
        if connection.execute(
            sa.select(shipments.c.id)
            .where(shipments.c.shipment_number == number)
            .limit(1)
        ).first():
            continue
        if connection.execute(
            insert(generated_shipment_numbers)
            .values(number=number)
            .on_conflict_do_nothing()
            .returning(generated_shipment_numbers.c.number)
        ).scalar_one_or_none():
            return number
    raise DomainError(503, "Shipment number generation failed", "number_generation")


def reuse_customer(
    connection: Connection, company_id: int, address: AddressInput
) -> int:
    values = address.model_dump()
    values["company"] = values.pop("name")
    row_id = connection.execute(
        insert(customers)
        .values(company_id=company_id, **values)
        .on_conflict_do_nothing(constraint="uq_customers_address")
        .returning(customers.c.id)
    ).scalar_one_or_none()
    if row_id is None:
        predicates = [customers.c.company_id == company_id]
        predicates.extend(
            customers.c[name] == values[name]
            for name in (
                "company",
                "address_one",
                "address_two",
                "city",
                "state",
                "zip",
            )
        )
        row_id = connection.execute(
            sa.select(customers.c.id).where(*predicates)
        ).scalar_one()
    return int(row_id)


def recipient_zone(
    connection: Connection, customer_id: int, company_id: int
) -> str | None:
    return connection.execute(
        sa.select(customers_validated.c.timezone)
        .select_from(
            customers.join(
                customers_validated,
                sa.and_(
                    customers.c.validated_id == customers_validated.c.id,
                    customers.c.company_id == customers_validated.c.company_id,
                ),
            )
        )
        .where(customers.c.id == customer_id, customers.c.company_id == company_id)
    ).scalar_one_or_none()


def shipment_dto(row: sa.RowMapping, timezone: str | None = None) -> ShipmentCreated:
    return ShipmentCreated(
        id=str(row["id"]),
        reference=row["shipper_ref"],
        shipment_number=row["shipment_number"],
        carrier_company_id=str(row["carrier_company_id"]),
        account_number=row["account_id"],
        reference_two=row["shipper_ref2"],
        service_name=row["service_type"],
        sender_id=str(row["sender_id"]),
        recipient_id=str(row["recipient_id"]),
        weight=row["weight"],
        due_time=display_instant(row["due_time"], timezone),
        due_date=row["due_date"],
        route=row["route"],
    )


def insert_shipment(
    connection: Connection,
    company_id: int,
    carrier_id: int,
    account: str,
    service: str,
    payload: ShipmentInput,
    *,
    number_factory: Callable[[], str] = random_number,
    processed_at: datetime | None = None,
    receipt: int | None = None,
    notes: str | None = None,
    order_date: date | None = None,
) -> sa.RowMapping:
    created_action = connection.execute(
        sa.select(shipment_actions.c.id).where(shipment_actions.c.action == "created")
    ).scalar_one_or_none()
    if created_action is None:
        raise DomainError(503, "Shipment catalog is not configured", "missing_catalog")
    # PostgreSQL transaction time anchors both the Created event/default.
    processed_at = (
        processed_at or connection.execute(sa.select(sa.func.now())).scalar_one()
    )
    sender_id = reuse_customer(connection, company_id, payload.from_address)
    recipient_id = reuse_customer(connection, company_id, payload.to_address)
    timezone = recipient_zone(connection, recipient_id, company_id)
    deadline = (
        normalize_instant(payload.due_time, timezone)
        if payload.due_time
        else default_deadline(processed_at)
    )
    number_lock(connection)
    number = payload.shipment_number or generate_number(connection, number_factory)
    row = (
        connection.execute(
            shipments.insert()
            .values(
                shipper_company_id=company_id,
                carrier_company_id=carrier_id,
                account_id=account,
                creation_service=service,
                shipper_ref=payload.reference,
                shipment_number=number,
                shipper_ref2=payload.reference_two,
                service_type=payload.service_name,
                sender_id=sender_id,
                recipient_id=recipient_id,
                weight=payload.package.weight if payload.package else None,
                due_time=deadline,
                due_date=deadline.date(),
                created_at=processed_at,
                updated_at=processed_at,
                notes=notes,
                order_date=order_date,
            )
            .returning(shipments)
        )
        .mappings()
        .one()
    )
    event_values = dict(
        shipment_id=row["id"],
        action_id=created_action,
        event_time=processed_at,
        created_at=processed_at,
    )
    if receipt is not None:
        event_values["receipt_order"] = receipt
    accepted_receipt = connection.execute(
        shipment_events.insert()
        .values(**event_values)
        .returning(shipment_events.c.receipt_order)
    ).scalar_one()
    for field in ("shipment_number", "notes", "due_time"):
        if row[field] is None:
            continue
        connection.execute(
            shipment_field_receipts.insert().values(
                shipment_id=row["id"], field_name=field, receipt_order=accepted_receipt
            )
        )
    return row


class ShipmentService:
    def __init__(
        self, engine: Engine, number_factory: Callable[[], str] = random_number
    ) -> None:
        self.engine = engine
        self.number_factory = number_factory

    def create(self, principal: Principal, payload: ShipmentInput) -> CreationResult:
        service, account = payload.required_assignment()
        with self.engine.begin() as connection:
            lock_tenant(connection, int(principal.company.id))
            company_id = shipper_scope(connection, principal)
            existing = (
                connection.execute(
                    sa.select(shipments).where(
                        shipments.c.shipper_company_id == company_id,
                        shipments.c.shipper_ref == payload.reference,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if (
                    service == existing["creation_service"]
                    and account == existing["account_id"]
                ):
                    company_type(connection, int(existing["carrier_company_id"]), 1)
                else:
                    creation_assignment(connection, company_id, service, account)
                timezone = recipient_zone(
                    connection, existing["recipient_id"], company_id
                )
                # D49: valid API retries return the original package unchanged.
                # Validate malformed supplied deadlines without applying corrections.
                if payload.due_time:
                    normalize_instant(
                        payload.due_time,
                        recipient_zone(
                            connection, existing["recipient_id"], company_id
                        ),
                    )
                return CreationResult(shipment_dto(existing, timezone), False)
            carrier_id = creation_assignment(connection, company_id, service, account)
            row = insert_shipment(
                connection,
                company_id,
                carrier_id,
                account,
                service,
                payload,
                number_factory=self.number_factory,
            )
            return CreationResult(
                shipment_dto(
                    row, recipient_zone(connection, row["recipient_id"], company_id)
                ),
                True,
            )

    def record_error(
        self,
        principal: Principal,
        code: str,
        reference: str | None = None,
        account: str | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            company_id = shipper_scope(connection, principal)
            connection.execute(
                ingestion_errors.insert().values(
                    shipper_company_id=company_id,
                    source_type="api_create",
                    reason_code=code,
                    received_reference=reference,
                    received_account=account,
                    user_id=int(principal.id),
                )
            )
