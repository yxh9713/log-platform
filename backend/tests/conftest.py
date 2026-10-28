import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from alembic import command
from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from tests.shipment_support import creation_client as creation_client
from tests.shipment_support import creation_env as creation_env


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("Set RUN_DB_TESTS=1 to use a disposable PostgreSQL test database")
    settings = DatabaseSettings()
    name = "p2_test_" + uuid.uuid4().hex
    test_url = (
        make_url(str(settings.database_url))
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(str(settings.database_url), autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                sql.Identifier(name)
            )
        )
    monkeypatch.setenv("DATABASE_URL", str(test_url))
    engine = create_database_engine(DatabaseSettings())
    try:
        yield engine
    finally:
        engine.dispose()
        with psycopg.connect(str(settings.database_url), autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def migrated_database(database: Engine) -> Engine:
    command.upgrade(Config("alembic.ini"), "head")
    return database
