from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from app.db.schema import company
from app.shipments.accounts import AccountMappingService
from app.shipments.areas import AreaService
from app.shipments.common import DomainError
from app.shipments.dto import AreaInput
from app.shipments.schema import (
    account_mapping,
    carrier_accounts,
    customers,
    customers_validated,
    generated_shipment_numbers,
    ingestion_errors,
    shipment_events,
    shipments,
)
from app.shipments.service import ShipmentService
from tests.shipment_support import CreationEnvironment, shipment_input

pytestmark = pytest.mark.integration


def count(engine: Engine, table: sa.Table) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                sa.select(sa.func.count()).select_from(table)
            ).scalar_one()
        )


def test_creation_defaults_address_reuse_and_one_created(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    result = ShipmentService(env.engine).create(env.regular, shipment_input())
    assert result.created
    assert len(result.shipment.shipment_number) == 15
    assert result.shipment.sender_id == result.shipment.recipient_id
    assert result.shipment.route is None and result.shipment.weight is None
    assert count(env.engine, customers) == 1
    assert count(env.engine, shipment_events) == 1
    with env.engine.connect() as connection:
        row = connection.execute(sa.select(shipments)).mappings().one()
        event = connection.execute(sa.select(shipment_events)).mappings().one()
        assert row["created_at"] == event["event_time"] == event["created_at"]
        assert row["order_date"] is None and row["pod_name"] is None
        assert row["due_time"].hour == 17 and row["due_time"].weekday() < 5
        assert row["due_date"] == row["due_time"].date()
        address = connection.execute(sa.select(customers)).mappings().one()
        assert address["zip"] == "00123" and address["address_two"] is None


def test_retry_returns_entire_existing_package_unchanged(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service = ShipmentService(env.engine)
    first = service.create(
        env.admin,
        shipment_input(
            shipment_number="SUPPLIED",
            package={"weight": "1.005"},
            reference_two="original",
            service_name="Original",
            due_time="2026-10-24",
        ),
    )
    retry = shipment_input(
        shipment_number="REPLACEMENT",
        package={"weight": "20"},
        reference_two="changed",
        service_name="Changed",
        due_time="2030-01-01",
        to_address={
            "name": "Different",
            "address_one": "2 Test Way",
            "city": "Elsewhere",
            "state": "TS",
            "zip": "00999",
        },
    )
    assert service.create(env.admin, retry).shipment == first.shipment
    assert not service.create(env.admin, retry).created
    assert (
        count(env.engine, customers)
        == count(env.engine, shipments)
        == count(env.engine, shipment_events)
        == 1
    )
    assert count(env.engine, generated_shipment_numbers) == 0


def test_reference_priority_and_tenant_address_isolation(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service = ShipmentService(env.engine)
    first = service.create(env.admin, shipment_input(shipment_number="REPEATED"))
    second = service.create(
        env.admin, shipment_input(reference="00002", shipment_number="REPEATED")
    )
    other = service.create(
        env.other, shipment_input(account_number="0008", shipment_number="REPEATED")
    )
    assert len({first.shipment.id, second.shipment.id, other.shipment.id}) == 3
    assert first.shipment.recipient_id == second.shipment.recipient_id
    assert first.shipment.recipient_id != other.shipment.recipient_id
    assert count(env.engine, shipment_events) == 3


def test_metadata_on_reused_addresses_is_not_overwritten(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    first_payload = shipment_input()
    first_payload.to_address.note = "first metadata"
    first_payload.from_address.note = "first metadata"
    first = ShipmentService(env.engine).create(env.admin, first_payload)
    new_payload = shipment_input(reference="00002")
    new_payload.to_address.note = "replacement metadata"
    second = ShipmentService(env.engine).create(env.admin, new_payload)
    assert first.shipment.recipient_id == second.shipment.recipient_id
    with env.engine.connect() as connection:
        assert (
            connection.execute(sa.select(customers.c.note)).scalar_one()
            == "first metadata"
        )


def test_concurrent_reference_and_customer_reuse(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service = ShipmentService(env.engine)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: service.create(env.admin, shipment_input()), range(4))
        )
    assert sum(result.created for result in results) == 1
    assert len({result.shipment.id for result in results}) == 1
    assert (
        count(env.engine, customers)
        == count(env.engine, shipments)
        == count(env.engine, shipment_events)
        == 1
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda index: service.create(
                    env.admin, shipment_input(reference=f"different-{index}")
                ),
                range(4),
            )
        )
    assert count(env.engine, customers) == 1 and count(env.engine, shipments) == 5


def test_generated_number_collision_reservation_and_rollback(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    ShipmentService(env.engine).create(
        env.admin, shipment_input(shipment_number="AAAAAAAAAAAAAAA")
    )
    candidates = iter(["AAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBB"])
    result = ShipmentService(env.engine, lambda: next(candidates)).create(
        env.admin, shipment_input(reference="00002")
    )
    assert result.shipment.shipment_number == "BBBBBBBBBBBBBBB"
    with pytest.raises(DomainError):
        ShipmentService(env.engine, lambda: "BBBBBBBBBBBBBBB").create(
            env.admin, shipment_input(reference="00003")
        )
    assert (
        count(env.engine, shipments) == 2
        and count(env.engine, generated_shipment_numbers) == 1
    )
    # Later supplied duplicates are permitted; only generated numbers reserve identity.
    ShipmentService(env.engine).create(
        env.admin, shipment_input(reference="00004", shipment_number="BBBBBBBBBBBBBBB")
    )
    assert count(env.engine, shipments) == 3


def test_mapping_future_only_and_historical_authorization(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service = ShipmentService(env.engine)
    old = service.create(env.admin, shipment_input())
    mapping = AccountMappingService(env.engine)
    mapping.configure(
        int(env.admin.company.id), env.carrier_id, "SECOND.SERVICE", "0007"
    )
    mapping.configure(int(env.admin.company.id), env.carrier_id, "TEST.SERVICE", "0009")
    retry = service.create(env.admin, shipment_input())
    new = service.create(
        env.admin, shipment_input(reference="00002", account_number="0009")
    )
    assert retry.shipment == old.shipment and new.shipment.account_number == "0009"
    with env.engine.connect() as connection:
        assert mapping.resolve_shipper(connection, env.carrier_id, "0007") == int(
            env.admin.company.id
        )
        assert mapping.resolve_shipper(connection, env.carrier_id, "0009") == int(
            env.admin.company.id
        )
    with pytest.raises(DomainError):
        mapping.configure(int(env.other.company.id), env.carrier_id, "CONFLICT", "0007")
    assert count(env.engine, account_mapping) == 3
    assert count(env.engine, carrier_accounts) == 3


def test_immutable_fields_and_tenant_fks(creation_env: CreationEnvironment) -> None:
    env = creation_env
    result = ShipmentService(env.engine).create(env.admin, shipment_input())
    other = ShipmentService(env.engine).create(
        env.other, shipment_input(account_number="0008")
    )
    other_area, _ = AreaService(env.engine).create(env.other, AreaInput(name="other"))
    invalid = [
        customers.update()
        .where(customers.c.id == int(result.shipment.sender_id))
        .values(city="Mutated"),
        shipments.update()
        .where(shipments.c.id == int(result.shipment.id))
        .values(sender_id=int(other.shipment.sender_id)),
        shipments.update()
        .where(shipments.c.id == int(result.shipment.id))
        .values(account_id="0008"),
        shipments.update()
        .where(shipments.c.id == int(result.shipment.id))
        .values(route=other_area.id),
    ]
    for statement in invalid:
        with pytest.raises(IntegrityError), env.engine.begin() as connection:
            connection.execute(statement)
    with env.engine.begin() as connection:
        validation_id = connection.execute(
            customers_validated.insert()
            .values(company_id=int(env.other.company.id), timezone="UTC")
            .returning(customers_validated.c.id)
        ).scalar_one()
    with pytest.raises(IntegrityError), env.engine.begin() as connection:
        connection.execute(
            customers.update()
            .where(customers.c.id == int(result.shipment.sender_id))
            .values(validated_id=validation_id)
        )


def test_deadline_timezone_and_invalid_atomicity(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service = ShipmentService(env.engine)
    first = service.create(env.admin, shipment_input())
    with env.engine.begin() as connection:
        validated = connection.execute(
            customers_validated.insert()
            .values(
                company_id=int(env.admin.company.id), timezone="America/Los_Angeles"
            )
            .returning(customers_validated.c.id)
        ).scalar_one()
        connection.execute(customers.update().values(validated_id=validated))
    second = service.create(
        env.admin, shipment_input(reference="00002", due_time="2026-10-20T17:00:00")
    )
    assert second.shipment.due_time.isoformat() == "2026-10-20T17:00:00-07:00"
    assert str(second.shipment.due_date) == "2026-10-21"
    before = count(env.engine, customers)
    with pytest.raises(DomainError):
        service.create(
            env.admin, shipment_input(reference="bad", due_time="2026-11-01T01:30:00")
        )
    assert count(env.engine, customers) == before and count(env.engine, shipments) == 2
    assert first.shipment.due_time.utcoffset() is not None
    with pytest.raises(DomainError):
        service.create(
            env.admin,
            shipment_input(
                reference="bad-new-address",
                due_time="invalid-date",
                to_address={
                    "name": "Unsaved recipient",
                    "address_one": "99 Test Way",
                    "city": "New City",
                    "state": "TS",
                    "zip": "00999",
                },
            ),
        )
    assert count(env.engine, customers) == before and count(env.engine, shipments) == 2


def test_area_crud_normalization_role_and_links(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service = AreaService(env.engine)
    sfo, created = service.create(env.admin, AreaInput(name="  SFO  "))
    assert created and sfo.name == "sfo"
    other, _ = service.create(env.admin, AreaInput(name="alpha"))
    assert [item.name for item in service.list(env.regular)] == ["alpha", "sfo"]
    assert service.rename(env.admin, sfo.id, AreaInput(name="alpha")) == sfo
    with pytest.raises(DomainError, match="sfo already exist"):
        service.create(env.admin, AreaInput(name="SFO"))
    result = ShipmentService(env.engine).create(env.admin, shipment_input())
    with env.engine.begin() as connection:
        connection.execute(
            shipments.update()
            .where(shipments.c.id == int(result.shipment.id))
            .values(route=sfo.id)
        )
    renamed = service.rename(env.admin, sfo.id, AreaInput(name="west"))
    assert renamed.id == sfo.id
    service.delete(env.admin, sfo.id)
    service.delete(env.admin, sfo.id)
    with pytest.raises(DomainError):
        service.rename(env.admin, sfo.id, AreaInput(name="deleted"))
    restored, created = service.create(env.admin, AreaInput(name="WEST"))
    assert not created and restored.id == sfo.id
    with env.engine.connect() as connection:
        assert connection.execute(sa.select(shipments.c.route)).scalar_one() == sfo.id
    with pytest.raises(DomainError):
        service.delete(env.regular, other.id)
    with pytest.raises(DomainError):
        service.delete(env.other, other.id)
    forged = env.regular.model_copy(update={"role": "administrator"})
    with pytest.raises(DomainError):
        service.create(forged, AreaInput(name="forged"))


def test_concurrent_area_names_and_unicode(creation_env: CreationEnvironment) -> None:
    env = creation_env
    service = AreaService(env.engine)

    def create(_: int) -> int:
        try:
            return service.create(env.admin, AreaInput(name=" SFO "))[0].id
        except DomainError as error:
            assert error.status == 400
            return -1

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(create, range(3)))
    assert sum(value > 0 for value in ids) == 1
    assert service.create(env.other, AreaInput(name="SFO"))[1]
    assert service.create(env.admin, AreaInput(name="Étage 1"))[0].name == "étage 1"


def test_creation_api_contract_and_diagnostics(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    headers = {"X-Requested-With": "logistics-web"}
    payload = shipment_input().model_dump(mode="json")
    response = client.post("/v1/shipments", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["reference"] == "00001"
    assert response.json()["due_time"].endswith("+00:00")
    assert (
        client.post("/v1/shipments", json=payload, headers=headers).status_code == 200
    )
    for bad, expected in [
        ({**payload, "account_number": None}, 400),
        ({**payload, "account_number": "wrong"}, 400),
        ({**payload, "due_time": "not-a-date"}, 400),
        ({**payload, "reference": 42}, 422),
        ({**payload, "shipper_company_id": env.other.company.id}, 422),
    ]:
        response = client.post("/v1/shipments", json=bad, headers=headers)
        assert response.status_code == expected
        assert "Test recipient" not in response.text
    assert count(env.engine, ingestion_errors) == 5
    with env.engine.connect() as connection:
        errors = connection.execute(sa.select(ingestion_errors)).mappings().all()
        assert all(
            row["shipper_company_id"] == int(env.admin.company.id)
            and row["user_id"] == int(env.admin.id)
            for row in errors
        )
        assert any(
            row["received_reference"] == "00001" and row["received_account"] == "wrong"
            for row in errors
        )
    assert count(env.engine, shipments) == count(env.engine, shipment_events) == 1
    response = client.post(
        "/v1/shipments", json={**payload, "account_number": None}, headers=headers
    )
    assert response.json() == {"message": "account is required"}
    assert client.post("/v1/shipments", json=payload).status_code == 403
    client.cookies.clear()
    assert client.post("/v1/shipments", json=payload).status_code == 401


def test_area_api_role_tenant_and_exact_responses(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    headers = {"X-Requested-With": "logistics-web"}
    response = client.post("/v1/area", json={"name": " SFO "}, headers=headers)
    assert response.status_code == 201
    output = response.json()
    assert client.get("/v1/areas").json() == [output]
    assert client.post("/v1/area", json={"name": "sfo"}, headers=headers).json() == {
        "message": "sfo already exist"
    }
    assert client.delete(f"/v1/area/{output['id']}", headers=headers).json() == {
        "message": "Area deleted"
    }
    assert client.delete(f"/v1/area/{output['id']}", headers=headers).status_code == 200
    assert client.get("/v1/areas").json() == []
    restored = client.post("/v1/area", json={"name": "sfo"}, headers=headers)
    assert restored.status_code == 200 and restored.json() == output
    client.post(
        "/v1/login",
        json={
            "email": env.regular.email,
            "password": env.passwords[env.regular.email],
            "slug": "paychex",
        },
    )
    assert client.get("/v1/areas").status_code == 200
    assert (
        client.post("/v1/area", json={"name": "blocked"}, headers=headers).status_code
        == 403
    )


def test_concurrent_generated_number_collision_across_tenants(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env

    def create(other: bool) -> str:
        candidates = iter(
            ["CCCCCCCCCCCCCCC", "DDDDDDDDDDDDDDD" if other else "EEEEEEEEEEEEEEE"]
        )
        return (
            ShipmentService(env.engine, lambda: next(candidates))
            .create(
                env.other if other else env.admin,
                shipment_input(account_number="0008" if other else "0007"),
            )
            .shipment.shipment_number
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        numbers = list(pool.map(create, [False, True]))
    assert len(set(numbers)) == 2 and "CCCCCCCCCCCCCCC" in numbers
    assert count(env.engine, generated_shipment_numbers) == 2


def test_mapping_same_account_across_carriers_and_concurrent_owner_conflict(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    mapping = AccountMappingService(env.engine)
    with env.engine.begin() as connection:
        carrier = connection.execute(
            company.insert()
            .values(name="Test carrier", slug="test-carrier", company_type=1)
            .returning(company.c.id)
        ).scalar_one()
    mapping.configure(int(env.other.company.id), carrier, "OTHER.SERVICE", "0007")

    def configure(other: bool) -> bool:
        try:
            mapping.configure(
                int(env.other.company.id if other else env.admin.company.id),
                env.carrier_id,
                "CONCURRENT",
                "unclaimed",
            )
            return True
        except DomainError as error:
            assert error.code == "account_conflict"
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(configure, [False, True])) == 1
    with env.engine.connect() as connection:
        assert mapping.resolve_shipper(connection, carrier, "0007") == int(
            env.other.company.id
        )
        assert mapping.resolve_shipper(connection, env.carrier_id, "0007") == int(
            env.admin.company.id
        )


def test_new_rows_cannot_cross_customer_tenants_and_events_dedupe(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    first = ShipmentService(env.engine).create(env.admin, shipment_input())
    other = ShipmentService(env.engine).create(
        env.other, shipment_input(account_number="0008")
    )
    with env.engine.connect() as connection:
        row = dict(
            connection.execute(
                sa.select(shipments).where(shipments.c.id == int(first.shipment.id))
            )
            .mappings()
            .one()
        )
        event = dict(
            connection.execute(
                sa.select(shipment_events).where(
                    shipment_events.c.shipment_id == int(first.shipment.id)
                )
            )
            .mappings()
            .one()
        )
    row.pop("id")
    row.update(shipper_ref="cross-tenant", sender_id=int(other.shipment.sender_id))
    with pytest.raises(IntegrityError), env.engine.begin() as connection:
        connection.execute(shipments.insert().values(**row))
    event.pop("id")
    event.pop("receipt_order")
    with pytest.raises(IntegrityError), env.engine.begin() as connection:
        connection.execute(shipment_events.insert().values(**event))
    with pytest.raises(IntegrityError), env.engine.begin() as connection:
        connection.execute(
            shipments.update()
            .where(shipments.c.id == int(first.shipment.id))
            .values(due_date="2000-01-01")
        )


def test_api_database_failure_is_sanitized(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    from typing import cast

    from fastapi import FastAPI
    from sqlalchemy.exc import SQLAlchemyError

    client, _ = creation_client
    with patch.object(
        cast(FastAPI, client.app).state.shipments,
        "create",
        side_effect=SQLAlchemyError("private SQL values"),
    ):
        response = client.post(
            "/v1/shipments",
            json=shipment_input().model_dump(mode="json"),
            headers={"X-Requested-With": "logistics-web"},
        )
    assert response.status_code == 503
    assert response.json() == {
        "message": "Shipment creation is temporarily unavailable"
    }


def test_failed_diagnostics_persistence_does_not_claim_success(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    from typing import cast

    from fastapi import FastAPI
    from sqlalchemy.exc import SQLAlchemyError

    client, env = creation_client
    with patch.object(
        cast(FastAPI, client.app).state.shipments,
        "record_error",
        side_effect=SQLAlchemyError("private database error"),
    ):
        response = client.post(
            "/v1/shipments",
            json=shipment_input(account_number=None).model_dump(mode="json"),
            headers={"X-Requested-With": "logistics-web"},
        )
    assert response.status_code == 503
    assert response.json() == {
        "message": "Shipment diagnostics are temporarily unavailable"
    }
    assert count(env.engine, shipments) == count(env.engine, customers) == 0


def test_area_http_edit_and_wrong_tenant_ids(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    headers = {"X-Requested-With": "logistics-web"}
    created = client.post("/v1/area", json={"name": "first"}, headers=headers).json()
    response = client.put(
        f"/v1/area/{created['id']}", json={"name": "SECOND"}, headers=headers
    )
    assert response.status_code == 200 and response.json() == {
        "id": created["id"],
        "name": "second",
    }
    other, _ = AreaService(env.engine).create(env.other, AreaInput(name="hidden"))
    assert (
        client.put(
            f"/v1/area/{other.id}", json={"name": "changed"}, headers=headers
        ).status_code
        == 404
    )
    assert client.delete(f"/v1/area/{other.id}", headers=headers).status_code == 404
    assert all(item["name"] != "hidden" for item in client.get("/v1/areas").json())
    assert (
        client.post(
            "/v1/area", json={"name": "invalid/name"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.delete("/v1/area/9223372036854775808", headers=headers).status_code
        == 422
    )
    schema = client.get("/openapi.json").json()
    assert {"200", "201", "400", "401", "403", "422", "503"} <= set(
        schema["paths"]["/v1/shipments"]["post"]["responses"]
    )
