import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.db.schema import company, metadata, shipment_actions, user_role, users
from app.db.seed import SeedResult, seed_database
from app.db.seed_data import DEVELOPMENT_DATA, CompanySeed, UserSeed
from app.passwords import hash_password, verify_password

pytestmark = pytest.mark.integration


def counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table.name: connection.execute(
                sa.select(sa.func.count()).select_from(table)
            ).scalar_one()
            for table in (company, user_role, shipment_actions, users)
        }


def test_migration_empty_repeat_downgrade_and_metadata(database: Engine) -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert set(sa.inspect(database).get_table_names()) == {
        "alembic_version",
        "ingestion_source",
        "ingestion_imports",
        "ingestion_rows",
        "shipment_field_receipts",
        "auth_sessions",
        "account_mapping",
        "area",
        "carrier_accounts",
        "integrations",
        "carrier_receipts",
        "shipment_images",
        "export_jobs",
        "customers",
        "customers_validated",
        "generated_shipment_numbers",
        "shipments",
        "shipment_events",
        "ingestion_errors",
        "company",
        "user_role",
        "users",
        "shipment_actions",
    }
    assert counts(database) == {
        "company": 0,
        "user_role": 0,
        "shipment_actions": 0,
        "users": 0,
    }
    with database.connect() as connection:
        assert connection.execute(sa.text("SHOW timezone")).scalar_one() == "UTC"
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []
    command.check(config)
    command.downgrade(config, "base")
    assert sa.inspect(database).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    assert counts(database)["users"] == 0


def test_seed_twice_hashes_and_foreign_keys(migrated_database: Engine) -> None:
    engine = migrated_database
    result = seed_database(engine)
    assert result.created == {
        "company": 2,
        "user_role": 2,
        "shipment_actions": 7,
        "users": 2,
    }
    assert len(result.credentials) == 2
    assert result.credentials[0].password != result.credentials[1].password
    with engine.connect() as connection:
        rows = (
            connection.execute(
                sa.select(
                    users.c.email,
                    users.c.password,
                    users.c.active,
                    company.c.slug,
                    company.c.company_type,
                    user_role.c.name,
                )
                .join(company)
                .join(user_role)
            )
            .mappings()
            .all()
        )
        initial_hashes = {row["email"]: row["password"] for row in rows}
        assert {(row["email"], row["name"], row["slug"]) for row in rows} == {
            ("admin@paychex.example", "administrator", "paychex"),
            ("user@paychex.example", "user", "paychex"),
        }
        for credential in result.credentials:
            assert verify_password(
                credential.password, initial_hashes[credential.email]
            )
        assert all(row["active"] and row["company_type"] == 2 for row in rows)
        assert set(
            connection.execute(sa.select(shipment_actions.c.action)).scalars()
        ) == set(DEVELOPMENT_DATA.actions)
    rerun = seed_database(engine)
    assert rerun.created == {}
    assert rerun.credentials == []
    assert rerun.existing == result.created
    with engine.connect() as connection:
        current_hashes = {
            email: password_hash
            for email, password_hash in connection.execute(
                sa.select(users.c.email, users.c.password)
            )
        }
        assert current_hashes == initial_hashes
    assert counts(engine) == result.created


def test_seed_preserves_manual_settings_and_promoted_user(
    migrated_database: Engine,
) -> None:
    engine = migrated_database
    seed_database(engine)
    with engine.begin() as connection:
        admin_id = connection.execute(
            sa.select(user_role.c.id).where(user_role.c.name == "administrator")
        ).scalar_one()
        connection.execute(
            users.update()
            .where(users.c.email == "user@paychex.example")
            .values(role_id=admin_id, active=False)
        )
        connection.execute(
            company.update()
            .where(company.c.slug == "paychex")
            .values(name="Locally edited", active=False)
        )
        connection.execute(
            company.insert().values(
                name="Manual company", slug="manual", company_type=2
            )
        )
    seed_database(engine)
    with engine.connect() as connection:
        row = (
            connection.execute(
                sa.select(users).where(users.c.email == "user@paychex.example")
            )
            .mappings()
            .one()
        )
        assert row["role_id"] == admin_id and row["active"] is False
        row = (
            connection.execute(sa.select(company).where(company.c.slug == "paychex"))
            .mappings()
            .one()
        )
        assert row["name"] == "Locally edited" and row["active"] is False
    assert counts(engine)["company"] == 3


def test_concurrent_seeds_create_once(migrated_database: Engine) -> None:
    engine = migrated_database
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: seed_database(engine), range(2)))
    assert sum(len(result.credentials) for result in results) == 2
    assert counts(engine) == {
        "company": 2,
        "user_role": 2,
        "shipment_actions": 7,
        "users": 2,
    }
    assert sum(result.created.get("users", 0) for result in results) == 2


def test_editable_declarations_and_tenant_email_identity(
    migrated_database: Engine,
) -> None:
    engine = migrated_database
    extra = replace(
        DEVELOPMENT_DATA,
        companies=(
            *DEVELOPMENT_DATA.companies,
            CompanySeed("Test shipper", "test-shipper", 2),
        ),
        users=(
            *DEVELOPMENT_DATA.users,
            UserSeed("test-shipper", "admin@paychex.example", "user"),
        ),
    )
    result = seed_database(engine, extra)
    assert len(result.credentials) == 3
    assert seed_database(engine, extra).credentials == []
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(users)
                .where(users.c.email == "admin@paychex.example")
            ).scalar_one()
            == 2
        )


def test_database_constraints(migrated_database: Engine) -> None:
    engine = migrated_database
    seed_database(engine)
    with engine.connect() as connection:
        company_id = connection.execute(
            sa.select(company.c.id).where(company.c.slug == "paychex")
        ).scalar_one()
        role_id = connection.execute(
            sa.select(user_role.c.id).where(user_role.c.name == "user")
        ).scalar_one()
    invalid = [
        company.insert().values(name="Invalid", slug="invalid", company_type=3),
        company.insert().values(name="Duplicate", slug="paychex", company_type=2),
        user_role.insert().values(name="administrator"),
        shipment_actions.insert().values(action="created"),
        users.insert().values(
            company_id=company_id,
            role_id=role_id,
            email="admin@paychex.example",
            password="test",
        ),
        users.insert().values(
            company_id=-1, role_id=role_id, email="nobody@example.test", password="test"
        ),
        users.insert().values(
            company_id=company_id,
            role_id=-1,
            email="nobody@example.test",
            password="test",
        ),
    ]
    for statement in invalid:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(statement)
    # Same hash is legal for different users: there is no unique password index.
    password_hash = hash_password("synthetic test password")
    with engine.begin() as connection:
        for email in ("one@example.test", "two@example.test"):
            connection.execute(
                users.insert().values(
                    company_id=company_id,
                    role_id=role_id,
                    email=email,
                    password=password_hash,
                )
            )
    columns = {
        column["name"]: column for column in sa.inspect(engine).get_columns("users")
    }
    for name in ("created_at", "updated_at"):
        column_type = columns[name]["type"]
        assert isinstance(column_type, sa.DateTime)
        assert column_type.timezone


def test_seed_rolls_back_if_credential_sink_fails(migrated_database: Engine) -> None:
    def fail(result: SeedResult) -> None:
        raise OSError("Simulated private-file failure")

    with pytest.raises(OSError):
        seed_database(migrated_database, before_commit=fail)
    assert counts(migrated_database) == {
        "company": 0,
        "user_role": 0,
        "shipment_actions": 0,
        "users": 0,
    }


def run_cli(
    *arguments: str, environment: str = "development"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.db.seed", *arguments],
        env={**os.environ, "APP_ENV": environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_private_output_guards_and_rerun(
    migrated_database: Engine, tmp_path: Path
) -> None:
    path = tmp_path / "initial.json"
    assert (
        run_cli("--credentials-file", str(path), environment="production").returncode
        == 1
    )
    assert not path.exists()
    assert run_cli().returncode == 1  # captured stdout is not an interactive terminal
    assert counts(migrated_database)["users"] == 0
    target = tmp_path / "target.txt"
    target.write_text("untouched")
    link = tmp_path / "symlink.json"
    link.symlink_to(target)
    assert run_cli("--credentials-file", str(link)).returncode == 1
    assert target.read_text() == "untouched"
    assert counts(migrated_database)["users"] == 0
    first = run_cli("--credentials-file", str(path))
    assert first.returncode == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    credentials = json.loads(path.read_text())["users"]
    assert len(credentials) == 2
    for item in credentials:
        assert item["password"] not in first.stdout + first.stderr
    assert run_cli("--credentials-file", str(path)).returncode == 1
    assert json.loads(path.read_text())["users"] == credentials
    rerun_path = tmp_path / "rerun.json"
    rerun = run_cli("--credentials-file", str(rerun_path))
    assert rerun.returncode == 0
    assert json.loads(rerun_path.read_text()) == {"users": []}
    assert counts(migrated_database)["users"] == 2


def test_cli_before_migration_is_sanitized(database: Engine, tmp_path: Path) -> None:
    path = tmp_path / "failed.json"
    result = run_cli("--credentials-file", str(path))
    assert result.returncode == 1
    assert "Seed failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert not path.exists()
    assert sa.inspect(database).get_table_names() == []
