from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.db.schema import metadata as metadata


def identity() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def created_at() -> sa.Column[datetime]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def updated_at() -> sa.Column[datetime]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


customers_validated = sa.Table(
    "customers_validated",
    metadata,
    identity(),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("timezone", sa.String(64)),
    sa.Column("latitude", sa.Numeric(9, 6)),
    sa.Column("longitude", sa.Numeric(9, 6)),
    sa.Column(
        "validation_metadata",
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
    sa.UniqueConstraint("id", "company_id", name="uq_customers_validated_id_company"),
    sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
    sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
)
customers = sa.Table(
    "customers",
    metadata,
    identity(),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("company", sa.String(255), nullable=False),
    sa.Column("address_one", sa.String(255), nullable=False),
    sa.Column("address_two", sa.String(255)),
    sa.Column("city", sa.String(128), nullable=False),
    sa.Column("state", sa.String(64), nullable=False),
    sa.Column("zip", sa.String(32), nullable=False),
    sa.Column("note", sa.Text),
    sa.Column("phone", sa.String(64)),
    sa.Column("email", sa.String(320)),
    sa.Column("validated_id", sa.BigInteger),
    created_at(),
    updated_at(),
    sa.UniqueConstraint("id", "company_id", name="uq_customers_id_company"),
    sa.UniqueConstraint(
        "company_id",
        "company",
        "address_one",
        "address_two",
        "city",
        "state",
        "zip",
        name="uq_customers_address",
        postgresql_nulls_not_distinct=True,
    ),
    sa.ForeignKeyConstraint(
        ["validated_id", "company_id"],
        ["customers_validated.id", "customers_validated.company_id"],
        name="fk_customers_validation_company",
    ),
    *[
        sa.CheckConstraint(
            f"{name} = btrim({name}) AND length({name}) > 0", name=f"{name}_normalized"
        )
        for name in ("company", "address_one", "city", "state", "zip")
    ],
    sa.CheckConstraint(
        "address_two IS NULL OR "
        "(address_two = btrim(address_two) AND length(address_two) > 0)",
        name="address_two_normalized",
    ),
)
carrier_accounts = sa.Table(
    "carrier_accounts",
    metadata,
    identity(),
    sa.Column("shipper_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("carrier_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("account_id", sa.String(255), nullable=False),
    created_at(),
    sa.UniqueConstraint(
        "carrier_company_id", "account_id", name="uq_carrier_accounts_pair"
    ),
    sa.UniqueConstraint(
        "carrier_company_id",
        "account_id",
        "shipper_company_id",
        name="uq_carrier_accounts_owner",
    ),
    sa.CheckConstraint(
        "account_id = btrim(account_id) AND length(account_id) > 0",
        name="account_normalized",
    ),
)
account_mapping = sa.Table(
    "account_mapping",
    metadata,
    identity(),
    sa.Column("shipper_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("carrier_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("account_id", sa.String(255), nullable=False),
    sa.Column("service", sa.String(64), nullable=False),
    created_at(),
    updated_at(),
    sa.UniqueConstraint(
        "shipper_company_id", "service", name="uq_account_mapping_shipper_service"
    ),
    sa.ForeignKeyConstraint(
        ["carrier_company_id", "account_id", "shipper_company_id"],
        [
            "carrier_accounts.carrier_company_id",
            "carrier_accounts.account_id",
            "carrier_accounts.shipper_company_id",
        ],
        name="fk_account_mapping_owner",
    ),
    sa.CheckConstraint(
        "service = btrim(service) AND length(service) > 0", name="service_normalized"
    ),
)
area = sa.Table(
    "area",
    metadata,
    identity(),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("name", sa.String(64), nullable=False),
    sa.Column("deleted_at", sa.DateTime(timezone=True)),
    created_at(),
    updated_at(),
    sa.UniqueConstraint("company_id", "name", name="uq_area_company_name"),
    sa.UniqueConstraint("id", "company_id", name="uq_area_id_company"),
    sa.CheckConstraint(
        "name = lower(btrim(name)) AND length(name) > 0 AND name ~ '^[[:alnum:] _-]+$'",
        name="name_normalized",
    ),
)
generated_shipment_numbers = sa.Table(
    "generated_shipment_numbers",
    metadata,
    sa.Column("number", sa.String(15), primary_key=True),
    created_at(),
    sa.CheckConstraint("number ~ '^[A-Z0-9]{12,15}$'", name="number_format"),
)
shipments = sa.Table(
    "shipments",
    metadata,
    identity(),
    sa.Column("shipper_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("carrier_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("account_id", sa.String(255), nullable=False),
    sa.Column("creation_service", sa.String(64), nullable=False),
    sa.Column("shipment_number", sa.String(255), nullable=False, index=True),
    sa.Column("shipper_ref", sa.String(255), nullable=False),
    sa.Column("shipper_ref2", sa.String(255)),
    sa.Column("service_type", sa.String(255)),
    sa.Column("sender_id", sa.BigInteger, nullable=False),
    sa.Column("recipient_id", sa.BigInteger, nullable=False),
    sa.Column("route", sa.BigInteger),
    sa.Column("weight", sa.Numeric(5, 2)),
    sa.Column("order_date", sa.Date),
    sa.Column("due_date", sa.Date, nullable=False),
    sa.Column("due_time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("deliver_time", sa.DateTime(timezone=True)),
    sa.Column("pod_name", sa.Text),
    sa.Column("notes", sa.Text),
    sa.Column("deleted_at", sa.DateTime(timezone=True)),
    created_at(),
    updated_at(),
    sa.UniqueConstraint(
        "shipper_company_id", "shipper_ref", name="uq_shipments_shipper_reference"
    ),
    sa.ForeignKeyConstraint(
        ["carrier_company_id", "account_id", "shipper_company_id"],
        [
            "carrier_accounts.carrier_company_id",
            "carrier_accounts.account_id",
            "carrier_accounts.shipper_company_id",
        ],
        name="fk_shipments_account_owner",
    ),
    sa.ForeignKeyConstraint(
        ["sender_id", "shipper_company_id"],
        ["customers.id", "customers.company_id"],
        name="fk_shipments_sender_company",
    ),
    sa.ForeignKeyConstraint(
        ["recipient_id", "shipper_company_id"],
        ["customers.id", "customers.company_id"],
        name="fk_shipments_recipient_company",
    ),
    sa.ForeignKeyConstraint(
        ["route", "shipper_company_id"],
        ["area.id", "area.company_id"],
        name="fk_shipments_route_company",
    ),
    sa.CheckConstraint("weight >= 0 AND weight <= 999.99", name="weight_range"),
    sa.CheckConstraint(
        "due_date = (due_time AT TIME ZONE 'UTC')::date", name="deadline_date"
    ),
    *[
        sa.CheckConstraint(
            f"{name} = btrim({name}) AND length({name}) > 0", name=f"{name}_normalized"
        )
        for name in ("shipper_ref", "shipment_number")
    ],
    sa.Index("ix_shipments_shipper_due_date", "shipper_company_id", "due_date", "id"),
)
receipt_order = sa.Sequence("shipment_receipt_order", metadata=metadata)
shipment_events = sa.Table(
    "shipment_events",
    metadata,
    identity(),
    sa.Column("shipment_id", sa.ForeignKey("shipments.id"), nullable=False),
    sa.Column("action_id", sa.ForeignKey("shipment_actions.id"), nullable=False),
    sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "receipt_order",
        sa.BigInteger,
        server_default=receipt_order.next_value(),
        nullable=False,
        unique=True,
    ),
    created_at(),
    sa.UniqueConstraint(
        "shipment_id", "action_id", "event_time", name="uq_shipment_events_exact"
    ),
    sa.Index(
        "ix_shipment_events_shipment_order",
        "shipment_id",
        "event_time",
        "receipt_order",
    ),
)
ingestion_errors = sa.Table(
    "ingestion_errors",
    metadata,
    identity(),
    sa.Column("shipper_company_id", sa.ForeignKey("company.id")),
    sa.Column("source_type", sa.String(64), nullable=False),
    sa.Column("reason_code", sa.String(64), nullable=False),
    sa.Column("received_reference", sa.String(255)),
    sa.Column("received_account", sa.String(255)),
    sa.Column("user_id", sa.ForeignKey("users.id")),
    sa.Column("shipment_id", sa.ForeignKey("shipments.id")),
    created_at(),
)
