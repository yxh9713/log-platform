"""Carrier authentication and durable synchronous webhook outcomes."""

from typing import Any

import sqlalchemy as sa

from app.ingestion.schema import metadata as metadata
from app.shipments.schema import ingestion_errors, shipment_events

integrations = sa.Table(
    "integrations",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("adapter", sa.String(64), nullable=False, server_default="ontrac"),
    sa.Column("apikey", sa.String(64), nullable=False),
    sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.CheckConstraint("adapter = 'ontrac'", name="adapter_supported"),
    sa.CheckConstraint("apikey ~ '^[a-f0-9]{64}$'", name="apikey_hash"),
)
carrier_receipts = sa.Table(
    "carrier_receipts",
    metadata,
    sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
    sa.Column("integration_id", sa.ForeignKey("integrations.id"), nullable=False),
    sa.Column("carrier_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("shipper_company_id", sa.ForeignKey("company.id")),
    sa.Column("shipment_id", sa.ForeignKey("shipments.id")),
    sa.Column("event_id", sa.ForeignKey("shipment_events.id")),
    sa.Column("receipt_order", sa.BigInteger, nullable=False, unique=True),
    sa.Column(
        "received_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.clock_timestamp(),
    ),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("reason_code", sa.String(64)),
    sa.CheckConstraint(
        "outcome IN ('accepted','duplicate','ignored','rejected')", name="outcome_valid"
    ),
    sa.CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'", name="request_hash_format"),
)
shipment_events.append_column(sa.Column("source_time", sa.String(128)))
shipment_events.append_column(sa.Column("normalization_zone", sa.String(64)))
sa.Index(
    "ix_shipment_events_source_time",
    shipment_events.c.shipment_id,
    shipment_events.c.action_id,
    shipment_events.c.source_time,
)
column: sa.Column[Any]
for column in (
    sa.Column("carrier_company_id", sa.ForeignKey("company.id")),
    sa.Column("integration_id", sa.ForeignKey("integrations.id")),
    sa.Column("carrier_receipt_id", sa.ForeignKey("carrier_receipts.id")),
):
    ingestion_errors.append_column(column)
