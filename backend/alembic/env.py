from alembic import context
from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.exports.schema import metadata


def run_migrations() -> None:
    # Deliberately online-only: obtain configuration without interpolating secrets
    # into alembic.ini or logging a connection URL.
    engine = create_database_engine(DatabaseSettings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline migration SQL is not supported; use a PostgreSQL database"
    )
run_migrations()
