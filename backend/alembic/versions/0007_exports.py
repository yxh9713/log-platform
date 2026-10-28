"""Durable requester-scoped CSV export queue and local artifact metadata."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_exports"
down_revision = "0006_pod_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("requester_id", sa.BigInteger(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("filename", sa.String(80)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("row_count", sa.BigInteger()),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'ready' AND filename IS NOT NULL "
            "AND size_bytes IS NOT NULL AND size_bytes >= 0 "
            "AND row_count IS NOT NULL AND row_count >= 0 "
            "AND content_hash IS NOT NULL) "
            "OR (state <> 'ready' AND filename IS NULL AND size_bytes IS NULL "
            "AND row_count IS NULL AND content_hash IS NULL)",
            name=op.f("ck_export_jobs_readiness_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('pending','retry_wait','ready','failed')",
            name=op.f("ck_export_jobs_state_valid"),
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 5", name=op.f("ck_export_jobs_attempts_valid")
        ),
        sa.CheckConstraint(
            "dismissed_at IS NULL OR state IN ('ready','failed')",
            name=op.f("ck_export_jobs_dismissal_valid"),
        ),
        sa.CheckConstraint(
            "filename IS NULL OR filename ~ "
            "'^shipment-[0-9]{4}-[0-9]{2}-[0-9]{2}\\.csv$'",
            name=op.f("ck_export_jobs_filename_valid"),
        ),
        sa.CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[a-f0-9]{64}$'",
            name=op.f("ck_export_jobs_hash_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name="fk_export_jobs_company_id_company"
        ),
        sa.ForeignKeyConstraint(
            ["requester_id", "company_id"],
            ["users.id", "users.company_id"],
            name="fk_export_jobs_requester_company",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_export_jobs"),
    )
    op.create_index(
        "ix_export_jobs_requester",
        "export_jobs",
        ["company_id", "requester_id", "created_at"],
    )
    op.create_index(
        "ix_export_jobs_pending", "export_jobs", ["state", "next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_table("export_jobs")
