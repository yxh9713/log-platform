"""Explicit development-only bootstrap: python -m app.db.seed."""

import argparse
import json
import os
import secrets
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.db.schema import company, shipment_actions, user_role, users
from app.db.seed_data import DEVELOPMENT_DATA, SeedData
from app.passwords import hash_password


@dataclass(frozen=True)
class InitialCredential:
    company_slug: str
    email: str
    password: str = field(repr=False)


@dataclass
class SeedResult:
    created: dict[str, int] = field(default_factory=dict)
    existing: dict[str, int] = field(default_factory=dict)
    credentials: list[InitialCredential] = field(default_factory=list, repr=False)

    def count(self, table: str, created: bool) -> None:
        counts = self.created if created else self.existing
        counts[table] = counts.get(table, 0) + 1


def validate_data(data: SeedData) -> None:
    def normalized(value: str, limit: int) -> bool:
        return bool(value) and value == value.strip().lower() and len(value) <= limit

    slugs = [item.slug for item in data.companies]
    identities = [(item.company_slug, item.email) for item in data.users]
    for values in (slugs, data.roles, data.actions, identities):
        if len(set(values)) != len(values):
            raise ValueError("Duplicate seed declaration identity")
    for item in data.companies:
        if (
            not normalized(item.slug, 64)
            or not item.name.strip()
            or len(item.name) > 255
            or item.company_type not in (1, 2)
        ):
            raise ValueError("Invalid company declaration")
    if any(not normalized(value, 64) for value in (*data.roles, *data.actions)):
        raise ValueError("Invalid catalog declaration")
    for user in data.users:
        if (
            user.company_slug not in slugs
            or user.role not in data.roles
            or not normalized(user.email, 320)
            or user.email.count("@") != 1
            or any(char.isspace() for char in user.email)
            or not all(user.email.split("@"))
        ):
            raise ValueError("Invalid user declaration or undeclared company/role")


def seed_database(
    engine: sa.Engine,
    data: SeedData = DEVELOPMENT_DATA,
    before_commit: Callable[[SeedResult], None] | None = None,
) -> SeedResult:
    validate_data(data)
    result = SeedResult()
    with engine.begin() as connection:
        # Serialize seed runs through commit; uniqueness also protects other writers.
        connection.execute(sa.text("SELECT pg_advisory_xact_lock(730012002)"))

        def ensure(
            table: sa.Table, identity: dict[str, Any], values: dict[str, Any]
        ) -> int:
            row_id = connection.execute(
                insert(table)
                .values(**identity, **values)
                .on_conflict_do_nothing(index_elements=list(identity))
                .returning(table.c.id)
            ).scalar_one_or_none()
            result.count(table.name, row_id is not None)
            if row_id is None:
                row_id = connection.execute(
                    sa.select(table.c.id).filter_by(**identity)
                ).scalar_one()
            return int(row_id)

        role_ids = {name: ensure(user_role, {"name": name}, {}) for name in data.roles}
        for action in data.actions:
            ensure(shipment_actions, {"action": action}, {})
        company_ids = {
            item.slug: ensure(
                company,
                {"slug": item.slug},
                {"name": item.name, "company_type": item.company_type},
            )
            for item in data.companies
        }
        for user in data.users:
            identity = {
                "company_id": company_ids[user.company_slug],
                "email": user.email,
            }
            if connection.execute(sa.select(users.c.id).filter_by(**identity)).first():
                result.count("users", False)
                continue
            password = secrets.token_urlsafe(24)
            row_id = connection.execute(
                insert(users)
                .values(
                    **identity,
                    role_id=role_ids[user.role],
                    password=hash_password(password),
                )
                .on_conflict_do_nothing(index_elements=["company_id", "email"])
                .returning(users.c.id)
            ).scalar_one_or_none()
            result.count("users", row_id is not None)
            if row_id is not None:
                result.credentials.append(
                    InitialCredential(user.company_slug, user.email, password)
                )
        if before_commit is not None:
            before_commit(result)
    return result


def credentials_json(result: SeedResult) -> str:
    return (
        json.dumps(
            {
                "users": [
                    {
                        "company_slug": item.company_slug,
                        "email": item.email,
                        "password": item.password,
                    }
                    for item in result.credentials
                ]
            },
            indent=2,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit development seed (never automatic)"
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help="Create a NEW private (0600) initial-credentials file",
    )
    args = parser.parse_args()
    destination: Path | None = args.credentials_file
    try:
        settings = DatabaseSettings()
    except ValidationError:
        print(
            "Invalid database/environment configuration; check local settings.",
            file=sys.stderr,
        )
        return 1
    if settings.app_env != "development":
        print("Seeding requires explicit APP_ENV=development.", file=sys.stderr)
        return 1
    if destination is None and not sys.stdout.isatty():
        print(
            "Use a terminal or --credentials-file; no credentials in logs.",
            file=sys.stderr,
        )
        return 1
    engine: sa.Engine | None = None
    created_file = False
    file_prepared = False
    try:
        engine = create_database_engine(settings)
        if destination is None:
            result = seed_database(engine)
        else:
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            created_file = True
            with os.fdopen(descriptor, "w") as stream:

                def write_credentials(result: SeedResult) -> None:
                    nonlocal file_prepared
                    stream.write(credentials_json(result))
                    stream.flush()
                    os.fsync(stream.fileno())
                    file_prepared = True

                # A failed private-file write aborts the database transaction.
                result = seed_database(engine, before_commit=write_credentials)
        print(json.dumps({"created": result.created, "existing": result.existing}))
        if destination is None and result.credentials:
            print("New development credentials (shown once):")
            print(credentials_json(result), end="")
        elif destination is not None:
            print("Initial credentials saved to the selected private file.")
        return 0
    except (OSError, ValueError, SQLAlchemyError):
        if created_file and not file_prepared and destination is not None:
            with suppress(OSError):
                destination.unlink(missing_ok=True)
        if file_prepared:
            print(
                "Private file retained; verify database state before rerunning.",
                file=sys.stderr,
            )
        # Do not echo driver errors, SQL parameters, hashes or generated passwords.
        print(
            "Seed failed. Check migrations, declarations and the NEW file destination.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
