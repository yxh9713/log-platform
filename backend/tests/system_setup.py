"""Explicit synthetic browser fixtures; refuses the development database."""

import hashlib
import json
from datetime import UTC, datetime, time

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.auth.dto import CompanyIdentity, Principal
from app.carriers.schema import integrations
from app.carriers.service import CarrierService
from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.db.schema import company, user_role, users
from app.db.seed import seed_database
from app.passwords import hash_password
from app.shipments.accounts import AccountMappingService
from app.shipments.areas import AreaService
from app.shipments.dto import AreaInput
from app.shipments.queries import reporting_day
from app.shipments.schema import shipments
from app.shipments.service import ShipmentService
from tests.shipment_support import shipment_input

# Public synthetic credential for this isolated disposable stack only.
PASSWORD = "synthetic-p12-browser-only"
KEY = "synthetic-p12-carrier-only"


def main() -> None:
    config = DatabaseSettings()
    engine = create_database_engine(config)
    with engine.connect() as connection:
        if (
            config.app_env != "test"
            or connection.execute(sa.text("SELECT current_database()")).scalar_one()
            != "logistics_p12"
        ):
            raise RuntimeError("System fixtures require the isolated P12 database")
    command.upgrade(Config("alembic.ini"), "head")
    seed_database(engine)
    second = seed_database(engine)
    assert not second.credentials and not any(second.created.values())
    with engine.begin() as connection:
        if connection.execute(
            sa.select(sa.func.count()).select_from(shipments)
        ).scalar_one():
            print(json.dumps({"system_fixture": "already_prepared"}))
            return
        tenant = connection.execute(
            sa.select(company.c.id).where(company.c.slug == "paychex")
        ).scalar_one()
        carrier = connection.execute(
            sa.select(company.c.id).where(company.c.slug == "ontrac")
        ).scalar_one()
        admin = connection.execute(
            sa.select(users.c.id, users.c.email)
            .join(user_role)
            .where(user_role.c.name == "administrator")
        ).one()
        connection.execute(users.update().values(password=hash_password(PASSWORD)))
        integration = connection.execute(
            integrations.insert()
            .values(company_id=carrier, apikey=hashlib.sha256(KEY.encode()).hexdigest())
            .returning(integrations.c.id)
        ).scalar_one()
        day = reporting_day(connection)
    principal = Principal(
        id=str(admin.id),
        email=admin.email,
        role="administrator",
        company=CompanyIdentity(id=str(tenant), name="Paychex", slug="paychex"),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    AccountMappingService(engine).configure(tenant, carrier, "TEST.SERVICE", "0007")
    AreaService(engine).create(principal, AreaInput(name="Empty area"))
    for ref in ("P12-0001", "P12-0002"):
        ShipmentService(engine).create(
            principal,
            shipment_input(
                reference=ref,
                shipment_number="P12-DUP",
                due_time=datetime.combine(day, time(23), UTC).isoformat(),
            ),
        )
    CarrierService(engine).receive(
        str(integration),
        KEY,
        dict(
            event="Delivered",
            account="0007",
            reference="P12-0001",
            time=datetime.combine(day, time(12), UTC).isoformat(),
            sign="Synthetic signer",
            route="West",
        ),
    )
    print(
        json.dumps(
            {
                "system_fixture": "prepared",
                "packages": 2,
                "seed_repeat_preserved": not any(second.created.values()),
                "integration_id": str(integration),
            }
        )
    )
    engine.dispose()


if __name__ == "__main__":
    main()
