from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import PostgresDsn, RedisDsn, SecretStr
from sqlalchemy import Engine

from app.auth.dto import CompanyIdentity, Principal
from app.auth.service import AuthService
from app.config import Settings
from app.db.schema import company, user_role, users
from app.db.seed import seed_database
from app.main import create_app
from app.passwords import hash_password
from app.shipments.accounts import AccountMappingService
from app.shipments.areas import AreaService
from app.shipments.dto import ShipmentInput
from app.shipments.service import ShipmentService


def shipment_input(**changes: Any) -> ShipmentInput:
    address = {
        "name": " Test recipient ",
        "address_one": " 1 Test Way ",
        "city": " Test City ",
        "state": "TS",
        "zip": "00123",
        "address_two": "  ",
    }
    return ShipmentInput.model_validate(
        {
            "reference": "00001",
            "account_number": "0007",
            "carrier_id": "TEST.SERVICE",
            "from_address": address,
            "to_address": address,
            **changes,
        }
    )


@dataclass(repr=False)
class CreationEnvironment:
    engine: Engine
    admin: Principal
    regular: Principal
    other: Principal
    carrier_id: int
    passwords: dict[str, str]


@pytest.fixture
def creation_env(migrated_database: Engine) -> CreationEnvironment:
    engine = migrated_database
    seeded = seed_database(engine)
    with engine.begin() as connection:
        shipper_id = connection.execute(
            sa.select(company.c.id).where(company.c.slug == "paychex")
        ).scalar_one()
        carrier_id = connection.execute(
            sa.select(company.c.id).where(company.c.slug == "ontrac")
        ).scalar_one()
        rows = connection.execute(
            sa.select(users.c.id, users.c.email, user_role.c.name).join(user_role)
        ).all()
        principals = {
            row.name: Principal(
                id=str(row.id),
                email=row.email,
                role=row.name,
                company=CompanyIdentity(
                    id=str(shipper_id), name="Paychex", slug="paychex"
                ),
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
            for row in rows
        }
        other_company = connection.execute(
            company.insert()
            .values(name="Test shipper", slug="test-shipper", company_type=2)
            .returning(company.c.id)
        ).scalar_one()
        role_id = connection.execute(
            sa.select(user_role.c.id).where(user_role.c.name == "administrator")
        ).scalar_one()
        other_user = connection.execute(
            users.insert()
            .values(
                company_id=other_company,
                role_id=role_id,
                email="other@example.test",
                password=hash_password("synthetic-unused-password"),
            )
            .returning(users.c.id)
        ).scalar_one()
    mapping = AccountMappingService(engine)
    mapping.configure(shipper_id, carrier_id, "TEST.SERVICE", "0007")
    mapping.configure(other_company, carrier_id, "TEST.SERVICE", "0008")
    other = Principal(
        id=str(other_user),
        email="other@example.test",
        role="administrator",
        company=CompanyIdentity(
            id=str(other_company), name="Test shipper", slug="test-shipper"
        ),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    return CreationEnvironment(
        engine,
        principals["administrator"],
        principals["user"],
        other,
        carrier_id,
        {item.email: item.password for item in seeded.credentials},
    )


@pytest.fixture
def creation_client(
    creation_env: CreationEnvironment,
) -> Iterator[tuple[TestClient, CreationEnvironment]]:
    env = creation_env
    settings = Settings(
        database_url=PostgresDsn(
            env.engine.url.set(drivername="postgresql").render_as_string(
                hide_password=False
            )
        ),
        redis_url=RedisDsn("redis://redis:6379/0"),
        app_env="test",
        auth_secret=SecretStr("synthetic-test-secret-" * 3),
    )
    app = create_app(settings)
    app.state.auth = AuthService(
        env.engine, settings.auth_secret.get_secret_value(), lambda ip, identity: True
    )
    app.state.shipments = ShipmentService(env.engine)
    app.state.areas = AreaService(env.engine)
    with TestClient(app) as client:
        response = client.post(
            "/v1/login",
            json={
                "email": env.admin.email,
                "password": env.passwords[env.admin.email],
                "slug": "paychex",
            },
        )
        assert response.status_code == 200
        yield client, env
