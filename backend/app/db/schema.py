"""Identity and session metadata; Alembic owns schema deployment."""

import sqlalchemy as sa

metadata = sa.MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

company = sa.Table(
    "company",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("slug", sa.String(64), nullable=False, unique=True),
    sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
    sa.Column("company_type", sa.SmallInteger, nullable=False),
    sa.CheckConstraint("company_type IN (1, 2)", name="company_type"),
    sa.CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),
    sa.CheckConstraint(
        "slug = lower(trim(slug)) AND length(slug) > 0", name="slug_normalized"
    ),
)
user_role = sa.Table(
    "user_role",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("name", sa.String(64), nullable=False, unique=True),
    sa.CheckConstraint(
        "name = lower(trim(name)) AND length(name) > 0", name="name_normalized"
    ),
)
users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False, index=True),
    sa.Column("role_id", sa.ForeignKey("user_role.id"), nullable=False, index=True),
    sa.Column("email", sa.String(320), nullable=False),
    sa.Column("password", sa.Text, nullable=False),
    sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
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
    sa.UniqueConstraint("company_id", "email", name="uq_users_company_email"),
    sa.UniqueConstraint("id", "company_id", name="uq_users_id_company"),
    sa.CheckConstraint(
        "email = lower(trim(email)) AND length(email) > 0", name="email_normalized"
    ),
    sa.CheckConstraint("length(password) > 0", name="password_nonempty"),
)
shipment_actions = sa.Table(
    "shipment_actions",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("action", sa.String(64), nullable=False, unique=True),
    sa.CheckConstraint(
        "action = lower(trim(action)) AND length(action) > 0", name="action_normalized"
    ),
)

auth_sessions = sa.Table(
    "auth_sessions",
    metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("company_id", sa.ForeignKey("company.id"), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    ),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.ForeignKeyConstraint(
        ["user_id", "company_id"],
        ["users.id", "users.company_id"],
        name="fk_auth_sessions_user_company",
        ondelete="CASCADE",
    ),
    sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_format"),
    sa.Index("ix_auth_sessions_user_id_company_id", "user_id", "company_id"),
)
