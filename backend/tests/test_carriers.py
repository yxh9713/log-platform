import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.carriers.schema import carrier_receipts, integrations
from app.carriers.service import CarrierService, process_event
from app.db.schema import company
from app.ingestion.cli import configure
from app.ingestion.schema import ingestion_imports, ingestion_rows
from app.ingestion.worker import IntakeWorker
from app.shipments.accounts import AccountMappingService
from app.shipments.areas import AreaService
from app.shipments.dto import AreaInput
from app.shipments.queries import QueryService
from app.shipments.query_dto import TrackingQuery
from app.shipments.schema import (
    area,
    customers,
    customers_validated,
    ingestion_errors,
    receipt_order,
    shipment_events,
    shipments,
)
from app.shipments.service import ShipmentService
from tests.shipment_support import CreationEnvironment, shipment_input
from tests.test_intake import make_due
from tests.test_manifest_rules import csv_bytes

pytestmark = pytest.mark.integration
KEY = "synthetic-carrier-key-used-only-in-tests"


def payload(**changes: Any) -> dict[str, Any]:
    return {
        "event": "Delivered",
        "account": "0007",
        "reference": "00001",
        "time": "2098-10-27T17:00:00Z",
        "sign": "Test signer",
        **changes,
    }


def prepare(env: CreationEnvironment) -> tuple[CarrierService, str]:
    ShipmentService(env.engine).create(env.admin, shipment_input())
    with env.engine.begin() as connection:
        identity = connection.execute(
            integrations.insert()
            .values(
                company_id=env.carrier_id,
                apikey=hashlib.sha256(KEY.encode()).hexdigest(),
            )
            .returning(integrations.c.id)
        ).scalar_one()
    return CarrierService(env.engine), str(identity)


def row(env: CreationEnvironment) -> sa.RowMapping:
    with env.engine.connect() as connection:
        return (
            connection.execute(
                sa.select(shipments).where(
                    shipments.c.shipper_company_id == int(env.admin.company.id)
                )
            )
            .mappings()
            .one()
        )


def count(env: CreationEnvironment, table: sa.Table) -> int:
    with env.engine.connect() as connection:
        return int(
            connection.execute(
                sa.select(sa.func.count()).select_from(table)
            ).scalar_one()
        )


@pytest.mark.parametrize(
    "mode",
    [
        "wrong",
        "missing",
        "unknown_id",
        "encoded_id",
        "shipper",
        "disabled",
        "carrier_disabled",
        "duplicate_header",
    ],
)
def test_key_boundary_precedes_body_and_creates_no_receipt(
    creation_client: tuple[TestClient, CreationEnvironment], mode: str
) -> None:
    client, env = creation_client
    _, integration = prepare(env)
    headers = {"X-API-Key": KEY, "Content-Type": "application/json"}
    if mode == "wrong":
        headers["X-API-Key"] = "wrong"
    if mode == "missing":
        del headers["X-API-Key"]
    if mode == "unknown_id":
        integration = "99999"
    if mode == "encoded_id":
        integration = "Mg=="
    with env.engine.begin() as connection:
        if mode == "shipper":
            connection.execute(
                integrations.update().values(company_id=int(env.admin.company.id))
            )
        if mode == "disabled":
            connection.execute(integrations.update().values(active=False))
        if mode == "carrier_disabled":
            connection.execute(
                company.update()
                .where(company.c.id == env.carrier_id)
                .values(active=False)
            )
    header_values = list(headers.items())
    if mode == "duplicate_header":
        header_values.append(("X-API-Key", KEY))
    response = client.post(
        f"/v1/webhook/{integration}", headers=header_values, content=b"malformed JSON"
    )
    assert response.status_code == 401 and response.json() == {
        "message": "Invalid API key"
    }
    assert count(env, carrier_receipts) == count(env, ingestion_errors) == 0
    assert count(env, shipment_events) == 1


def test_webhook_acceptance_rotation_replacement_and_cross_key(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    service, integration = prepare(env)
    response = client.post(
        f"/v1/webhook/{integration}",
        headers={"X-API-Key": KEY},
        json=payload(notes="carrier notes", route=" SFO ", shipment_number="000NEW"),
    )
    assert response.status_code == 200 and response.json()["outcome"] == "accepted"
    assert response.headers["cache-control"] == "no-store"
    package = row(env)
    assert (
        package["shipment_number"] == "000NEW" and package["notes"] == "carrier notes"
    )
    assert package["deliver_time"] == datetime(2098, 10, 27, 17, tzinfo=UTC)
    assert (
        QueryService(env.engine).detail(env.admin, package["id"]).status == "Delivered"
    )
    with env.engine.begin() as connection:
        assert connection.execute(sa.select(area.c.name)).scalar_one() == "sfo"
        connection.execute(
            integrations.update().values(
                apikey=hashlib.sha256(b"replacement-test-key").hexdigest()
            )
        )
        other_id = connection.execute(
            integrations.insert()
            .values(
                company_id=env.carrier_id,
                apikey=hashlib.sha256(KEY.encode()).hexdigest(),
            )
            .returning(integrations.c.id)
        ).scalar_one()
    assert (
        client.post(
            f"/v1/webhook/{integration}", headers={"X-API-Key": KEY}, json=payload()
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"/v1/webhook/{other_id}",
            headers={"X-API-Key": "replacement-test-key"},
            json=payload(),
        ).status_code
        == 401
    )
    assert (
        service.receive(integration, "replacement-test-key", payload())[1].outcome
        == "duplicate"
    )


def test_duplicates_unknowns_and_auxiliary_changes_have_no_effects(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    assert service.receive(integration, KEY, payload())[1].outcome == "accepted"
    original = dict(row(env))
    changed = payload(
        sign="Other",
        notes="wrong",
        shipment_number="wrong",
        route="new-area",
        due_time="invalid",
        pod="not image",
    )
    assert service.receive(integration, KEY, changed)[1].outcome == "duplicate"
    assert (
        service.receive(
            integration,
            KEY,
            {
                **changed,
                "event": "unknown",
                "time": "invalid",
                "account": "unknown",
                "reference": "missing",
            },
        )[1].outcome
        == "ignored"
    )
    assert dict(row(env)) == original and count(env, area) == 0
    assert count(env, shipment_events) == 2 and count(env, carrier_receipts) == 3
    assert count(env, ingestion_errors) == 0


def test_tenant_account_carrier_and_reference_priority(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    ShipmentService(env.engine).create(
        env.other, shipment_input(account_number="0008", shipment_number="000NUMBER")
    )
    assert (
        service.receive(
            integration, KEY, payload(account="0008", shipment_number="000NUMBER")
        )[1].outcome
        == "accepted"
    )
    assert row(env)["deliver_time"] is None
    result = service.receive(
        integration, KEY, payload(reference="000NUMBER", shipment_number="000NUMBER")
    )
    assert result[2] and result[2].code == "unmatched_shipment"
    result = service.receive(integration, KEY, payload(account="does-not-exist"))
    assert result[2] and result[2].code == "unknown_account"
    with env.engine.begin() as connection:
        carrier = connection.execute(
            company.insert()
            .values(name="Other carrier", slug="other-carrier", company_type=1)
            .returning(company.c.id)
        ).scalar_one()
    AccountMappingService(env.engine).configure(
        int(env.admin.company.id), carrier, "OTHER.SERVICE", "0007"
    )
    with env.engine.begin() as connection:
        other_integration = connection.execute(
            integrations.insert()
            .values(company_id=carrier, apikey=hashlib.sha256(KEY.encode()).hexdigest())
            .returning(integrations.c.id)
        ).scalar_one()
    result = service.receive(str(other_integration), KEY, payload())
    assert result[2] and result[2].code == "unmatched_shipment"
    assert count(env, shipments) == 2 and count(env, shipment_events) == 3
    with env.engine.connect() as connection:
        errors = connection.execute(sa.select(ingestion_errors)).mappings().all()
        assert len(errors) == 3 and all(
            error["source_type"] == "carrier_webhook" for error in errors
        )
        assert errors[0]["shipper_company_id"] == int(env.admin.company.id)
        assert errors[1]["shipper_company_id"] is None


def test_history_terminal_order_ties_and_incomplete_delivery(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(sign=None))
    package = row(env)
    assert (
        package["deliver_time"]
        and QueryService(env.engine).detail(env.admin, package["id"]).status
        == "Undelivered"
    )
    service.receive(
        integration,
        KEY,
        payload(event="Exception", time="2098-10-28T17:00:00Z", sign="Signer"),
    )
    assert (
        QueryService(env.engine).detail(env.admin, package["id"]).status == "Delivered"
    )
    service.receive(
        integration, KEY, payload(event="Returned", time="2098-10-29T17:00:00Z")
    )
    assert (
        QueryService(env.engine).detail(env.admin, package["id"]).status
        == "Undelivered"
    )
    assert row(env)["deliver_time"] == package["deliver_time"]
    service.receive(integration, KEY, payload(time="2098-10-30T17:00:00Z"))
    service.receive(
        integration, KEY, payload(event="Exception", time="2098-10-31T17:00:00Z")
    )
    service.receive(
        integration,
        KEY,
        payload(time="2098-10-26T17:00:00Z", notes="late ordinary correction"),
    )
    assert (
        QueryService(env.engine).detail(env.admin, package["id"]).status == "Delivered"
    )
    assert row(env)["deliver_time"] == datetime(2098, 10, 30, 17, tzinfo=UTC)
    assert row(env)["notes"] == "late ordinary correction"
    service.receive(
        integration, KEY, payload(event="Returned", time="2098-10-30T17:00:00Z")
    )
    assert (
        QueryService(env.engine).detail(env.admin, package["id"]).status
        == "Undelivered"
    )
    service.receive(
        integration, KEY, payload(time="2098-10-30T17:00:00Z", sign="duplicate")
    )
    assert (
        QueryService(env.engine).detail(env.admin, package["id"]).status
        == "Undelivered"
    )
    service.receive(integration, KEY, payload(time="2098-11-01T17:00:00Z"))
    assert (
        QueryService(env.engine).detail(env.admin, package["id"]).status == "Delivered"
    )
    with env.engine.begin() as connection:
        connection.execute(shipments.update().values(deleted_at=sa.func.now()))
    assert QueryService(env.engine).detail(env.admin, package["id"]).status == "Void"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"due_time": "bad"}, "invalid_source_time"),
        ({"route": "wrong!"}, "invalid_area"),
        ({"reference": "unknown"}, "unmatched_shipment"),
        ({"time": "2026-10-27"}, "invalid_event_time"),
    ],
)
def test_invalid_rows_are_atomic_and_durable(
    creation_env: CreationEnvironment, changes: dict[str, Any], code: str
) -> None:
    env = creation_env
    service, integration = prepare(env)
    original = dict(row(env))
    _, result, error = service.receive(
        integration,
        KEY,
        payload(**{"notes": "must rollback", "route": "new", **changes}),
    )
    assert result.outcome == "rejected" and error and error.code == code
    assert (
        dict(row(env)) == original
        and count(env, area) == 0
        and count(env, shipment_events) == 1
    )
    assert count(env, ingestion_errors) == 1


def test_deleted_route_reuse_and_missing_values_preserve(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    area_service = AreaService(env.engine)
    saved, _ = area_service.create(env.admin, AreaInput(name="SFO"))
    area_service.delete(env.admin, saved.id)
    original = dict(row(env))
    service.receive(
        integration,
        KEY,
        payload(route=" SFO ", notes="notes", shipment_number="000NEW"),
    )
    service.receive(
        integration,
        KEY,
        payload(
            event="Exception",
            time="2098-10-28T17:00:00Z",
            route="",
            notes=None,
            sign="",
            shipment_number=None,
        ),
    )
    after = row(env)
    assert (
        after["route"] == saved.id
        and after["notes"] == "notes"
        and after["pod_name"] == "Test signer"
        and after["shipment_number"] == "000NEW"
    )
    assert (
        after["sender_id"] == original["sender_id"]
        and after["recipient_id"] == original["recipient_id"]
    )
    with env.engine.connect() as connection:
        assert connection.execute(sa.select(area.c.deleted_at)).scalar_one() is not None
    assert area_service.list(env.admin) == []


def test_reverse_execution_receipts_and_concurrent_exact_duplicates(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    with env.engine.begin() as connection:
        older = connection.execute(sa.select(receipt_order.next_value())).scalar_one()
        newer = connection.execute(sa.select(receipt_order.next_value())).scalar_one()
        process_event(
            connection,
            env.carrier_id,
            payload(
                event="Returned",
                route="new",
                notes="new",
                sign="New",
                due_time="2098-12-02",
            ),
            newer,
        )
    with env.engine.begin() as connection:
        process_event(
            connection,
            env.carrier_id,
            payload(route="old", notes="old", sign="Old", due_time="2098-12-01"),
            older,
        )
    after = row(env)
    assert (
        after["notes"] == "new"
        and after["pod_name"] == "New"
        and str(after["due_date"]) == "2098-12-02"
    )
    assert (
        QueryService(env.engine).detail(env.admin, after["id"]).status == "Undelivered"
    )
    assert count(env, area) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(
            pool.map(
                lambda _: service.receive(
                    integration, KEY, payload(time="2098-11-03T17:00:00Z")
                )[1].outcome,
                range(4),
            )
        )
    assert outcomes.count("accepted") == 1 and outcomes.count("duplicate") == 3


def test_timezone_normalization_and_retry_after_zone_change(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    with env.engine.begin() as connection:
        validation = connection.execute(
            customers_validated.insert()
            .values(
                company_id=int(env.admin.company.id), timezone="America/Los_Angeles"
            )
            .returning(customers_validated.c.id)
        ).scalar_one()
        connection.execute(customers.update().values(validated_id=validation))
    service.receive(
        integration,
        KEY,
        payload(time="2026-10-27T17:00:00", due_time="2026-10-27T18:00:00"),
    )
    assert row(env)["deliver_time"] == datetime(2026, 10, 28, 0, tzinfo=UTC)
    with env.engine.begin() as connection:
        connection.execute(
            customers_validated.update().values(timezone="America/New_York")
        )
    assert (
        service.receive(integration, KEY, payload(time="2026-10-27T17:00:00"))[
            1
        ].outcome
        == "duplicate"
    )
    assert row(env)["deliver_time"] == datetime(2026, 10, 28, 0, tzinfo=UTC)
    assert (
        service.receive(integration, KEY, payload(time="2026-11-01T01:30:00"))[2]
        is not None
    )


def test_invalid_image_retains_no_partial_effects(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    _, result, error = service.receive(
        integration,
        KEY,
        payload(pod="image-stage-pending", route="new", notes="not committed"),
    )
    assert result.outcome == "rejected" and error and error.code == "invalid_pod_image"
    assert row(env)["deliver_time"] is None and count(env, area) == 0
    assert count(env, shipment_events) == 1 and count(env, carrier_receipts) == 1


def test_carrier_csv_partial_duplicates_unknowns_and_no_delayed_matching(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    prepare(env)
    ShipmentService(env.engine).create(env.other, shipment_input(account_number="0008"))
    configure(env.engine, "ontrac", adapter="ontrac_csv")
    folder = tmp_path / "ontrac" / "upload"
    folder.mkdir(parents=True)
    data = {
        "account": "0007",
        "reference": "00001",
        "event": "Delivery",
        "timestamp": "10/27/2098 5:00:00 PM",
        "zone": "154",
        "shipment_number": "000CSV",
        "sign": "CSV signer",
        "notes": "notes",
        "due_time": "",
        "status": "ignored",
        "address_one": "must not update",
        "pod_image": "",
    }
    content = csv_bytes(
        data,
        data,
        {**data, "event": "unknown", "reference": "missing", "due_time": "bad"},
        {**data, "account": "0008", "event": "Possession"},
        {**data, "reference": "later"},
        {**data, "event": "Exception", "timestamp": "10/28/2098 5:00:00 PM"},
    )
    path = folder / "carrier.part"
    path.write_bytes(content)
    worker = IntakeWorker(env.engine, tmp_path)
    worker.tick(force=True)
    assert count(env, ingestion_imports) == 0
    path.rename(folder / "carrier.csv")
    worker.tick(force=True)
    with env.engine.connect() as connection:
        run = connection.execute(sa.select(ingestion_imports)).mappings().one()
        assert (
            run["state"] == "completed_with_errors"
            and run["rows_completed"] == 5
            and run["rows_rejected"] == 1
        )
        assert (
            run["rows_duplicate"] == 1
            and run["rows_ignored"] == 1
            and run["archive_path"].startswith("failed/")
        )
        error = connection.execute(sa.select(ingestion_errors)).mappings().one()
        assert (
            error["shipper_company_id"] == int(env.admin.company.id)
            and error["carrier_company_id"] == env.carrier_id
        )
        assert error["row_number"] == 6 and error["received_account"] == "0007"
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(ingestion_rows)
            ).scalar_one()
            == 6
        )
    assert row(env)["shipment_number"] == "000CSV" and count(env, area) == 2
    ShipmentService(env.engine).create(env.admin, shipment_input(reference="later"))
    worker.tick(force=True)
    assert count(env, shipment_events) == 6  # three Created + three carrier events
    (folder / "renamed.csv").write_bytes(content)
    worker.tick(force=True)
    assert count(env, shipment_events) == 6


def test_carrier_csv_retry_does_not_replace_newer_manifest_fields(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    from tests.test_intake import upload
    from tests.test_manifest_rules import manifest_row

    env = creation_env
    prepare(env)
    configure(env.engine, "ontrac", adapter="ontrac_csv")
    folder = tmp_path / "ontrac" / "upload"
    folder.mkdir(parents=True)
    (folder / "one.csv").write_bytes(
        csv_bytes(
            {
                "account": "0007",
                "reference": "00001",
                "event": "Delivery",
                "timestamp": "10/27/2098 5:00:00 PM",
                "notes": "older",
            }
        )
    )
    worker = IntakeWorker(env.engine, tmp_path)
    with patch("app.ingestion.worker.load_carrier", side_effect=SQLAlchemyError()):
        worker.tick(force=True)
    configure(env.engine, "paychex")
    upload(
        tmp_path, "paychex", "new.csv", manifest_row(**{"Destination Notes": "newer"})
    )
    worker.tick(force=True)
    make_due(env)
    worker.tick(force=True)
    assert row(env)["notes"] == "newer"


def test_webhook_errors_limits_openapi_and_database_failure(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    _, integration = prepare(env)
    url = f"/v1/webhook/{integration}"
    headers = {"X-API-Key": KEY, "Content-Type": "application/json"}
    for content in (
        b"{",
        b"[]",
        b'{"event":"Delivery","event":"Returned"}',
        b'{"event":NaN}',
    ):
        response = client.post(url, headers=headers, content=content)
        assert response.status_code == 400 and response.json() == {
            "message": "Invalid carrier JSON"
        }
    assert client.post(url, headers={"X-API-Key": KEY}, content=b"x").status_code == 415
    response = client.post(url, headers=headers, content=b"x" * 7_000_001)
    assert response.status_code == 413 and count(env, carrier_receipts) == 0
    response = client.post(
        url, headers={"X-API-Key": KEY}, json=payload(reference="missing")
    )
    assert response.status_code == 400 and count(env, ingestion_errors) == 1
    with patch.object(
        cast(FastAPI, client.app).state.carriers,
        "receive",
        side_effect=SQLAlchemyError("private data"),
    ):
        response = client.post(url, headers={"X-API-Key": KEY}, json=payload())
    assert response.status_code == 503 and "private" not in response.text
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/v1/webhook/{integrationId}"]["post"]
    assert operation["security"] == [{"APIKeyHeader": []}]
    assert "requestBody" in operation and {
        "200",
        "400",
        "401",
        "413",
        "415",
        "503",
    } <= set(operation["responses"])


def test_metrics_reflect_carrier_final_delivery_and_strict_deadline(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(due_time="2098-10-27T17:00:00Z"))
    query = TrackingQuery(start_date=date(2098, 10, 27), end_date=date(2098, 10, 27))
    result = QueryService(env.engine).tracking(env.admin, query)
    assert (
        result.metrics.total == result.metrics.delivered == 1
        and result.metrics.otp == 0
    )
    service.receive(
        integration,
        KEY,
        payload(
            event="Possession",
            time="2098-10-28T17:00:00Z",
            due_time="2098-10-27T18:00:00Z",
        ),
    )
    result = QueryService(env.engine).tracking(env.admin, query)
    assert result.metrics.otp == 100
    service.receive(
        integration, KEY, payload(event="Returned", time="2098-10-29T17:00:00Z")
    )
    result = QueryService(env.engine).tracking(env.admin, query)
    assert result.metrics.undelivered == 1 and result.metrics.delivered == 0
    assert result.items[0].deliver_time is not None


def test_key_replaced_while_reading_body_is_rechecked(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    _, integration = prepare(env)
    api_service = cast(FastAPI, client.app).state.carriers
    original = api_service.authenticate

    def replace_key(raw_id: str, key: str | None) -> None:
        original(raw_id, key)
        with env.engine.begin() as connection:
            connection.execute(
                integrations.update().values(
                    apikey=hashlib.sha256(b"rotated-during-upload").hexdigest()
                )
            )

    with patch.object(api_service, "authenticate", side_effect=replace_key):
        response = client.post(
            f"/v1/webhook/{integration}", headers={"X-API-Key": KEY}, json=payload()
        )
    assert response.status_code == 401 and response.json() == {
        "message": "Invalid API key"
    }
    assert count(env, carrier_receipts) == 0 and count(env, shipment_events) == 1


def test_historical_accounts_stay_authorized_and_inactive_shippers_fail(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    AccountMappingService(env.engine).configure(
        int(env.admin.company.id), env.carrier_id, "TEST.SERVICE", "9999"
    )
    assert service.receive(integration, KEY, payload())[1].outcome == "accepted"
    with env.engine.begin() as connection:
        connection.execute(
            company.update()
            .where(company.c.id == int(env.admin.company.id))
            .values(active=False)
        )
    _, result, error = service.receive(
        integration, KEY, payload(event="Exception", time="2098-10-28T17:00:00Z")
    )
    assert result.outcome == "rejected" and error and error.code == "invalid_assignment"
    assert count(env, shipment_events) == 2


def test_csv_crash_resume_keeps_row_order_and_skips_committed_events(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    from app.integrations.carriers.ontrac.loader import load as actual_load
    from tests.test_intake import Crash

    env = creation_env
    prepare(env)
    configure(env.engine, "ontrac", adapter="ontrac_csv")
    folder = tmp_path / "ontrac" / "upload"
    folder.mkdir(parents=True)
    first = {
        "account": "0007",
        "reference": "00001",
        "event": "Exception",
        "timestamp": "10/27/2098 5:00:00 PM",
    }
    (folder / "history.csv").write_bytes(
        csv_bytes(first, {**first, "timestamp": "10/28/2098 5:00:00 PM"})
    )
    seen = 0

    def crashing(*args: Any) -> Any:
        nonlocal seen
        seen += 1
        if seen == 2:
            raise Crash()
        return actual_load(*args)

    with (
        patch("app.ingestion.worker.load_carrier", side_effect=crashing),
        pytest.raises(Crash),
    ):
        IntakeWorker(env.engine, tmp_path).tick(force=True)
    with env.engine.connect() as connection:
        before = list(
            connection.execute(
                sa.select(ingestion_rows.c.receipt_order).order_by(
                    ingestion_rows.c.row_number
                )
            ).scalars()
        )
    IntakeWorker(env.engine, tmp_path).tick(force=True)
    with env.engine.connect() as connection:
        assert before == list(
            connection.execute(
                sa.select(ingestion_rows.c.receipt_order).order_by(
                    ingestion_rows.c.row_number
                )
            ).scalars()
        )
        run = connection.execute(sa.select(ingestion_imports)).mappings().one()
        assert run["state"] == "completed" and run["rows_completed"] == 2
    assert count(env, shipment_events) == 3


def test_csv_invalid_image_rejects_only_that_row(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    prepare(env)
    configure(env.engine, "ontrac", adapter="ontrac_csv")
    folder = tmp_path / "ontrac" / "upload"
    folder.mkdir(parents=True)
    item = {
        "account": "0007",
        "reference": "00001",
        "event": "Delivery",
        "timestamp": "10/27/2098 5:00:00 PM",
        "pod_image": "not-yet-supported",
        "sign": "Image signer",
    }
    (folder / "images.csv").write_bytes(
        csv_bytes(
            item,
            {
                **item,
                "event": "Exception",
                "timestamp": "10/28/2098 5:00:00 PM",
                "pod_image": "",
                "sign": "",
            },
        )
    )
    IntakeWorker(env.engine, tmp_path).tick(force=True)
    with env.engine.connect() as connection:
        run = connection.execute(sa.select(ingestion_imports)).mappings().one()
        assert (
            run["state"] == "completed_with_errors"
            and run["rows_rejected"] == run["rows_completed"] == 1
        )
        assert (
            connection.execute(sa.select(ingestion_errors.c.reason_code)).scalar_one()
            == "invalid_pod_image"
        )
    assert count(env, shipment_events) == 2 and row(env)["deliver_time"] is None
