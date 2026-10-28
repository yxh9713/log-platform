import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.pod.schema import metadata as metadata
from app.shipments.schema import created_at, updated_at

jobs = sa.Table(
    "export_jobs",
    metadata,
    sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column("requester_id", sa.BigInteger, nullable=False),
    sa.Column("filters", JSONB, nullable=False),
    sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "next_attempt_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("reason_code", sa.String(64)),
    sa.Column("filename", sa.String(80)),
    sa.Column("size_bytes", sa.BigInteger),
    sa.Column("row_count", sa.BigInteger),
    sa.Column("content_hash", sa.String(64)),
    sa.Column("dismissed_at", sa.DateTime(timezone=True)),
    created_at(),
    updated_at(),
    sa.ForeignKeyConstraint(
        ["requester_id", "company_id"],
        ["users.id", "users.company_id"],
        name="fk_export_jobs_requester_company",
    ),
    sa.CheckConstraint(
        "state IN ('pending','retry_wait','ready','failed')", name="state_valid"
    ),
    sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="attempts_valid"),
    sa.CheckConstraint(
        "(state = 'ready' AND filename IS NOT NULL "
        "AND size_bytes IS NOT NULL AND size_bytes >= 0 "
        "AND row_count IS NOT NULL AND row_count >= 0 "
        "AND content_hash IS NOT NULL) "
        "OR (state <> 'ready' AND filename IS NULL AND size_bytes IS NULL "
        "AND row_count IS NULL AND content_hash IS NULL)",
        name="readiness_valid",
    ),
    sa.CheckConstraint(
        "dismissed_at IS NULL OR state IN ('ready','failed')", name="dismissal_valid"
    ),
    sa.CheckConstraint(
        "filename IS NULL OR filename ~ '^shipment-[0-9]{4}-[0-9]{2}-[0-9]{2}\\.csv$'",
        name="filename_valid",
    ),
    sa.CheckConstraint(
        "content_hash IS NULL OR content_hash ~ '^[a-f0-9]{64}$'", name="hash_valid"
    ),
    sa.Index("ix_export_jobs_requester", "company_id", "requester_id", "created_at"),
    sa.Index("ix_export_jobs_pending", "state", "next_attempt_at"),
)
