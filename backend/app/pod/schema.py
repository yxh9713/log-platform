"""Event-linked POD history and a durable prepared-content storage queue."""

import sqlalchemy as sa

from app.carriers.schema import metadata as metadata
from app.shipments.schema import ingestion_errors, shipment_events, shipments

shipments.append_constraint(
    sa.UniqueConstraint("id", "shipper_company_id", name="uq_shipments_image_tenant")
)
shipment_events.append_constraint(
    sa.UniqueConstraint("id", "shipment_id", name="uq_shipment_events_image_owner")
)
shipment_images = sa.Table(
    "shipment_images",
    metadata,
    sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
    sa.Column("shipment_id", sa.BigInteger, nullable=False),
    sa.Column("shipper_company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("event_id", sa.BigInteger, nullable=False, unique=True),
    sa.Column("object_key", sa.String(255), nullable=False, unique=True),
    sa.Column("content_type", sa.String(32), nullable=False),
    sa.Column("width", sa.Integer, nullable=False),
    sa.Column("height", sa.Integer, nullable=False),
    sa.Column("input_size", sa.Integer, nullable=False),
    sa.Column("size_bytes", sa.Integer, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("prepared_content", sa.LargeBinary),
    sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("url", sa.Text),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("reason_code", sa.String(64)),
    sa.Column(
        "next_attempt_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.ForeignKeyConstraint(
        ["shipment_id", "shipper_company_id"],
        ["shipments.id", "shipments.shipper_company_id"],
        name="fk_shipment_images_tenant",
    ),
    sa.ForeignKeyConstraint(
        ["event_id", "shipment_id"],
        ["shipment_events.id", "shipment_events.shipment_id"],
        name="fk_shipment_images_event_owner",
    ),
    sa.CheckConstraint(
        "content_type IN ('image/jpeg','image/png')", name="format_valid"
    ),
    sa.CheckConstraint(
        "width BETWEEN 1 AND 900 AND height BETWEEN 1 AND 20000",
        name="dimensions_valid",
    ),
    sa.CheckConstraint(
        "input_size BETWEEN 1 AND 5000000 AND size_bytes BETWEEN 1 AND 20000000",
        name="sizes_valid",
    ),
    sa.CheckConstraint("content_hash ~ '^[a-f0-9]{64}$'", name="hash_valid"),
    sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="attempts_valid"),
    sa.CheckConstraint(
        "state IN ('pending','retry_wait','ready','failed')", name="state_valid"
    ),
    sa.CheckConstraint(
        "(state = 'ready' AND url IS NOT NULL AND prepared_content IS NULL) "
        "OR (state <> 'ready' AND url IS NULL AND prepared_content IS NOT NULL)",
        name="readiness_valid",
    ),
    sa.CheckConstraint(
        "prepared_content IS NULL OR octet_length(prepared_content) = size_bytes",
        name="prepared_size_valid",
    ),
    sa.Index("ix_shipment_images_work", "state", "next_attempt_at"),
)

ingestion_errors.append_column(
    sa.Column("image_id", sa.ForeignKey("shipment_images.id"))
)
