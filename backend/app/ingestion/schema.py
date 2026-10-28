"""Durable source/import/row state; raw CSV remains in restricted local storage."""

import sqlalchemy as sa

from app.shipments.schema import ingestion_errors, receipt_order
from app.shipments.schema import metadata as metadata


def identity() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


ingestion_source = sa.Table(
    "ingestion_source",
    metadata,
    identity(),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False, unique=True),
    sa.Column("folder", sa.String(64), nullable=False, unique=True),
    sa.Column("adapter", sa.String(64), nullable=False),
    sa.Column("poll_interval_seconds", sa.Integer, nullable=False, server_default="60"),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column(
        "next_poll_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.CheckConstraint("folder ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="folder_safe"),
    sa.CheckConstraint(
        "adapter IN ('paychex_manifest','ontrac_csv')", name="adapter_supported"
    ),
    sa.CheckConstraint(
        "poll_interval_seconds BETWEEN 1 AND 86400", name="poll_interval"
    ),
)
ingestion_imports = sa.Table(
    "ingestion_imports",
    metadata,
    sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
    sa.Column("source_id", sa.ForeignKey("ingestion_source.id"), nullable=False),
    sa.Column("original_name", sa.String(255), nullable=False),
    sa.Column("file_identity", sa.String(255), nullable=False),
    sa.Column("checksum", sa.String(64), nullable=True),
    sa.Column("dedupe_of_id", sa.Uuid(as_uuid=False)),
    sa.Column(
        "received_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("processing_date", sa.Date, nullable=False),
    sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
    sa.Column("reason_code", sa.String(64)),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "next_attempt_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("rows_total", sa.Integer, nullable=False, server_default="0"),
    sa.Column("rows_completed", sa.Integer, nullable=False, server_default="0"),
    sa.Column("rows_rejected", sa.Integer, nullable=False, server_default="0"),
    sa.Column("rows_ignored", sa.Integer, nullable=False, server_default="0"),
    sa.Column("rows_duplicate", sa.Integer, nullable=False, server_default="0"),
    sa.Column("materialized", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("archive_state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("archive_path", sa.Text),
    sa.Column("archive_attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "archive_next_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint(
        "source_id",
        "original_name",
        "file_identity",
        name="uq_ingestion_imports_arrival",
    ),
    sa.UniqueConstraint("id", "source_id", name="uq_ingestion_imports_source"),
    sa.ForeignKeyConstraint(
        ["dedupe_of_id", "source_id"],
        ["ingestion_imports.id", "ingestion_imports.source_id"],
        name="fk_ingestion_imports_dedupe_source",
    ),
    sa.CheckConstraint(
        "rows_ignored >= 0 AND rows_duplicate >= 0 "
        "AND rows_ignored + rows_duplicate <= rows_completed",
        name="outcome_counters",
    ),
    sa.CheckConstraint("checksum ~ '^[a-f0-9]{64}$'", name="checksum_format"),
    sa.CheckConstraint(
        "state IN ('pending','processing','retry_wait','completed',"
        "'completed_with_errors','failed','duplicate_waiting','skipped')",
        name="state_valid",
    ),
    sa.CheckConstraint(
        "archive_state IN ('pending','retry_wait','exhausted','completed')",
        name="archive_state_valid",
    ),
    sa.CheckConstraint(
        "attempts >= 0 AND archive_attempts >= 0 AND rows_completed >= 0 "
        "AND rows_rejected >= 0 AND rows_completed + rows_rejected <= rows_total",
        name="counters_valid",
    ),
    sa.Index(
        "uq_ingestion_imports_content",
        "source_id",
        "checksum",
        unique=True,
        postgresql_where=sa.text("dedupe_of_id IS NULL"),
    ),
    sa.Index("ix_ingestion_imports_pending", "source_id", "next_attempt_at"),
)
ingestion_rows = sa.Table(
    "ingestion_rows",
    metadata,
    sa.Column(
        "import_id",
        sa.Uuid(as_uuid=False),
        sa.ForeignKey("ingestion_imports.id"),
        primary_key=True,
    ),
    sa.Column("row_number", sa.Integer, primary_key=True),
    sa.Column(
        "receipt_order",
        sa.BigInteger,
        server_default=receipt_order.next_value(),
        nullable=False,
        unique=True,
    ),
    sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("shipment_id", sa.ForeignKey("shipments.id")),
    sa.Column("outcome", sa.String(16)),
    sa.CheckConstraint(
        "outcome IN ('accepted','duplicate','ignored')", name="outcome_valid"
    ),
    sa.Column("reason_code", sa.String(64)),
    sa.CheckConstraint("row_number >= 2", name="row_number_valid"),
    sa.CheckConstraint(
        "state IN ('pending','completed','rejected')", name="state_valid"
    ),
)
shipment_field_receipts = sa.Table(
    "shipment_field_receipts",
    metadata,
    sa.Column("shipment_id", sa.ForeignKey("shipments.id"), primary_key=True),
    sa.Column("field_name", sa.String(64), primary_key=True),
    sa.Column("receipt_order", sa.BigInteger, nullable=False),
    sa.CheckConstraint(
        "field_name IN ('shipment_number','notes','due_time','route','pod_name')",
        name="field_valid",
    ),
    sa.CheckConstraint("receipt_order > 0", name="receipt_positive"),
)
# Errors may refer to files without a matched shipment or a valid row.

for column in (
    sa.Column("source_id", sa.BigInteger),
    sa.Column("import_id", sa.Uuid(as_uuid=False)),
    sa.Column("row_number", sa.Integer),
):
    ingestion_errors.append_column(column)
ingestion_errors.append_constraint(
    sa.ForeignKeyConstraint(
        ["import_id", "source_id"],
        ["ingestion_imports.id", "ingestion_imports.source_id"],
        name="fk_ingestion_errors_import_source",
    )
)
ingestion_errors.append_constraint(
    sa.ForeignKeyConstraint(
        ["source_id"], ["ingestion_source.id"], name="fk_ingestion_errors_source"
    )
)
ingestion_errors.append_constraint(
    sa.ForeignKeyConstraint(
        ["import_id", "row_number"],
        ["ingestion_rows.import_id", "ingestion_rows.row_number"],
        name="fk_ingestion_errors_row",
    )
)
