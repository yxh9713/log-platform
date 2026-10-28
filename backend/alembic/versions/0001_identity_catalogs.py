"""P2 company, role, user and action schema; no development data."""

import sqlalchemy as sa

from alembic import op

revision = "0001_identity_catalogs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("company_type", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_company"),
        sa.UniqueConstraint("slug", name="uq_company_slug"),
        sa.CheckConstraint(
            "company_type IN (1, 2)", name=op.f("ck_company_company_type")
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name=op.f("ck_company_name_nonempty")
        ),
        sa.CheckConstraint(
            "slug = lower(trim(slug)) AND length(slug) > 0",
            name=op.f("ck_company_slug_normalized"),
        ),
    )
    op.create_table(
        "user_role",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_role"),
        sa.UniqueConstraint("name", name="uq_user_role_name"),
        sa.CheckConstraint(
            "name = lower(trim(name)) AND length(name) > 0",
            name=op.f("ck_user_role_name_normalized"),
        ),
    )
    op.create_table(
        "shipment_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_actions"),
        sa.UniqueConstraint("action", name="uq_shipment_actions_action"),
        sa.CheckConstraint(
            "action = lower(trim(action)) AND length(action) > 0",
            name=op.f("ck_shipment_actions_action_normalized"),
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name="fk_users_company_id_company"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["user_role.id"], name="fk_users_role_id_user_role"
        ),
        sa.UniqueConstraint("company_id", "email", name="uq_users_company_email"),
        sa.CheckConstraint(
            "email = lower(trim(email)) AND length(email) > 0",
            name=op.f("ck_users_email_normalized"),
        ),
        sa.CheckConstraint(
            "length(password) > 0", name=op.f("ck_users_password_nonempty")
        ),
    )
    op.create_index("ix_users_company_id", "users", ["company_id"])
    op.create_index("ix_users_role_id", "users", ["role_id"])


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("shipment_actions")
    op.drop_table("user_role")
    op.drop_table("company")
