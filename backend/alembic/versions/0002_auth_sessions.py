"""P3 durable shipper sessions; credentials/tokens are never seeded."""

import sqlalchemy as sa

from alembic import op

revision = "0002_auth_sessions"
down_revision = "0001_identity_catalogs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_users_id_company", "users", ["id", "company_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name="pk_auth_sessions"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name="fk_auth_sessions_company_id_company"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "company_id"],
            ["users.id", "users.company_id"],
            name="fk_auth_sessions_user_company",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_auth_sessions_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_auth_sessions_token_hash_format"),
        ),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index(
        "ix_auth_sessions_user_id_company_id",
        "auth_sessions",
        ["user_id", "company_id"],
    )


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_constraint("uq_users_id_company", "users", type_="unique")
