"""Shared trusted-ingestion transaction boundary; transport owns row checkpoints."""

from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from app.ingestion.schema import shipment_field_receipts
from app.integrations.shippers.paychex.transformer import ManifestRecord
from app.shipments.accounts import company_type
from app.shipments.common import DomainError, lock_tenant
from app.shipments.schema import account_mapping, shipments
from app.shipments.service import insert_shipment, number_lock, recipient_zone
from app.shipments.time_rules import normalize_instant


def apply_fields(
    connection: Connection, shipment_id: int, values: dict[str, Any], receipt: int
) -> None:
    """A missing field does not suppress an older receipt for another field."""
    changed: dict[str, Any] = {}
    for name, value in values.items():
        if value is None:
            continue
        guard = connection.execute(
            insert(shipment_field_receipts)
            .values(
                shipment_id=shipment_id,
                field_name=name,
                receipt_order=receipt,
            )
            .on_conflict_do_update(
                index_elements=["shipment_id", "field_name"],
                set_={"receipt_order": receipt},
                where=shipment_field_receipts.c.receipt_order < receipt,
            )
            .returning(shipment_field_receipts.c.receipt_order)
        ).scalar_one_or_none()
        if guard is not None:
            changed[name] = value
            if name == "due_time":
                changed["due_date"] = value.date()
    if changed:
        if "shipment_number" in changed:
            number_lock(connection)
        connection.execute(
            shipments.update()
            .where(shipments.c.id == shipment_id)
            .values(**changed, updated_at=sa.func.now())
        )


def manifest_upsert(
    connection: Connection,
    company_id: int,
    record: ManifestRecord,
    processed_at: datetime,
    receipt: int,
) -> int:
    lock_tenant(connection, company_id)
    company_type(connection, company_id, 2)
    payload = record.payload
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
    mapping = (
        connection.execute(
            sa.select(account_mapping).where(
                account_mapping.c.shipper_company_id == company_id,
                account_mapping.c.service == payload.carrier_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        # Mapping edits are future-only. Retain authorization for the original
        # selector; a different selector must still resolve to this assignment.
        if payload.carrier_id != existing["creation_service"] and (
            mapping is None
            or (mapping["carrier_company_id"], mapping["account_id"])
            != (existing["carrier_company_id"], existing["account_id"])
        ):
            raise DomainError(400, "Invalid manifest assignment", "invalid_assignment")
        company_type(connection, existing["carrier_company_id"], 1)
        zone = recipient_zone(connection, existing["recipient_id"], company_id)
        deadline = (
            normalize_instant(payload.due_time, zone) if payload.due_time else None
        )
        # Validate supplied order timestamp, while D50 preserves the stored value.
        if record.order_time:
            normalize_instant(record.order_time, zone)
        apply_fields(
            connection,
            existing["id"],
            {
                "shipment_number": payload.shipment_number,
                "notes": record.notes,
                "due_time": deadline,
            },
            receipt,
        )
        return int(existing["id"])
    if mapping is None:
        raise DomainError(400, "Unknown manifest service", "invalid_assignment")
    company_type(connection, mapping["carrier_company_id"], 1)
    # Shared creation resolves tenant address reuse/timezone atomically. Order date
    # is set only after that lookup, in this same transaction.
    row = insert_shipment(
        connection,
        company_id,
        mapping["carrier_company_id"],
        mapping["account_id"],
        str(payload.carrier_id),
        payload,
        processed_at=processed_at,
        receipt=receipt,
        notes=record.notes,
    )
    if record.order_time:
        order_date: date = normalize_instant(
            record.order_time,
            recipient_zone(connection, row["recipient_id"], company_id),
        ).date()
        connection.execute(
            shipments.update()
            .where(shipments.c.id == row["id"])
            .values(order_date=order_date)
        )
    return int(row["id"])
