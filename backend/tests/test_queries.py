from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.db.schema import shipment_actions, users
from app.shipments.areas import AreaService
from app.shipments.common import DomainError
from app.shipments.dto import AreaInput
from app.shipments.queries import QueryService
from app.shipments.query_dto import SearchQuery, TrackingQuery
from app.shipments.schema import (
    customers,
    customers_validated,
    ingestion_errors,
    shipment_events,
    shipments,
)
from app.shipments.service import ShipmentService
from tests.shipment_support import CreationEnvironment, shipment_input

DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def window(**changes: Any) -> TrackingQuery:
    return TrackingQuery(start_date=DAY, end_date=DAY, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": "2026-10-20"},
        {"end_date": "2026-10-20"},
        {"start_date": "2026-10-21", "end_date": "2026-10-20"},
        {"start_date": "2026-02-29", "end_date": "2026-03-01"},
        {"start_date": "1792454400", "end_date": "2026-10-20"},
        {"status": "void"},
        {"exception": "held"},
        {"date_type": "bogus"},
        {"sort": "private SQL"},
        {"direction": "descending"},
        {"export": 2},
        {"page": 0},
        {"length": 101},
        {"area": [0]},
        {"area": [2**63]},
        {"shipper_company_id": 1},
    ],
)
def test_query_validation(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TrackingQuery.model_validate(changes)


def test_search_query_exact_string_and_defaults() -> None:
    query = SearchQuery(identifier="  000A  ")
    assert query.identifier == "000A" and query.field == "reference"
    assert TrackingQuery().date_type == "due_date" and TrackingQuery().length == 10
    assert TrackingQuery.model_validate({"export": "0"}).export == 0
    for identifier in ("  ", 42):
        with pytest.raises(ValidationError):
            SearchQuery(identifier=identifier)


def make(env: CreationEnvironment, reference: str, **changes: Any) -> int:
    shipment_id = int(
        ShipmentService(env.engine)
        .create(
            env.admin,
            shipment_input(
                reference=reference,
                shipment_number="000NUM",
                due_time="2026-10-20T17:00:00Z",
                **changes,
            ),
        )
        .shipment.id
    )
    # Synthetic historical creation precedes the independently seeded history.
    with env.engine.begin() as connection:
        connection.execute(
            shipment_events.update()
            .where(shipment_events.c.shipment_id == shipment_id)
            .values(event_time=NOW - timedelta(days=2))
        )
    return shipment_id


def update(env: CreationEnvironment, shipment_id: int, **changes: Any) -> None:
    with env.engine.begin() as connection:
        connection.execute(
            shipments.update().where(shipments.c.id == shipment_id).values(**changes)
        )


def event(
    env: CreationEnvironment, shipment_id: int, action: str, at: datetime
) -> None:
    with env.engine.begin() as connection:
        action_id = connection.execute(
            sa.select(shipment_actions.c.id).where(shipment_actions.c.action == action)
        ).scalar_one()
        connection.execute(
            shipment_events.insert().values(
                shipment_id=shipment_id, action_id=action_id, event_time=at
            )
        )


@pytest.mark.integration
def test_dates_paging_sort_and_full_result_metrics(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service = QueryService(env.engine)
    ids = [make(env, ref) for ref in ("0001", "0002", "0003")]
    for index, item in enumerate(ids):
        update(env, item, deliver_time=NOW + timedelta(hours=index), pod_name="Signer")
    # Exactly equal is late, even when both values exist.
    update(env, ids[2], deliver_time=datetime(2026, 10, 20, 17, tzinfo=UTC))
    result = service.tracking(env.regular, window(length=1, page=2))
    assert [item.id for item in result.items] == [str(ids[1])]
    assert result.total == 3 and result.pages == 3
    assert result.metrics.model_dump() == {
        "total": 3,
        "delivered": 3,
        "undelivered": 0,
        "void": 0,
        "otp": 66.67,
    }
    assert service.tracking(env.admin, window(page=99)).items == []
    descending = service.tracking(env.admin, window(sort="reference", direction="desc"))
    assert [item.reference for item in descending.items] == ["0003", "0002", "0001"]
    assert (
        service.tracking(
            env.admin,
            TrackingQuery(
                start_date=DAY + timedelta(days=1), end_date=DAY + timedelta(days=1)
            ),
        ).total
        == 0
    )
    with env.engine.connect() as connection:
        today = connection.execute(
            sa.select(sa.cast(sa.func.timezone("UTC", sa.func.now()), sa.Date))
        ).scalar_one()
    update(
        env,
        ids[0],
        due_time=datetime.combine(today, datetime.min.time(), UTC),
        due_date=today,
    )
    default = service.tracking(env.admin, TrackingQuery())
    assert default.start_date == default.end_date == today
    assert str(ids[0]) in [row.id for row in default.items]


@pytest.mark.integration
@pytest.mark.parametrize("date_type", ["order_date", "deliver_time"])
def test_inclusive_date_and_timestamp_boundaries(
    creation_env: CreationEnvironment, date_type: str
) -> None:
    env = creation_env
    ids = [make(env, f"range-{i}") for i in range(4)]
    values = [
        datetime(2026, 10, 19, 23, 59, 59, 999999, UTC),
        datetime(2026, 10, 20, tzinfo=UTC),
        datetime(2026, 10, 20, 23, 59, 59, 999999, UTC),
        datetime(2026, 10, 21, tzinfo=UTC),
    ]
    for item, value in zip(ids, values, strict=True):
        update(
            env,
            item,
            **{date_type: value.date() if date_type == "order_date" else value},
        )
    assert [
        row.id
        for row in QueryService(env.engine)
        .tracking(env.admin, window(date_type=date_type))
        .items
    ] == [str(item) for item in ids[1:3]]
    # Max-date timestamp query must not overflow while preparing its exclusive bound.
    assert (
        QueryService(env.engine)
        .tracking(
            env.admin,
            TrackingQuery(
                start_date=date.max, end_date=date.max, date_type="deliver_time"
            ),
        )
        .total
        == 0
    )


@pytest.mark.integration
def test_area_or_account_and_cross_tenant_filter_validation(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    areas = AreaService(env.engine)
    a, _ = areas.create(env.admin, AreaInput(name="A"))
    b, _ = areas.create(env.admin, AreaInput(name="B"))
    gone, _ = areas.create(env.admin, AreaInput(name="gone"))
    foreign, _ = areas.create(env.other, AreaInput(name="foreign"))
    ids = [make(env, f"area-{i}") for i in range(4)]
    for item, route in zip(ids[:3], (a.id, b.id, gone.id), strict=True):
        update(env, item, route=route)
    areas.delete(env.admin, gone.id)
    service = QueryService(env.engine)
    assert service.tracking(env.admin, window()).total == 4
    result = service.tracking(
        env.admin, window(area=[a.id, b.id, a.id], account="0007")
    )
    assert result.total == 2 and result.metrics.otp == 100
    assert service.tracking(env.admin, window(area=[a.id], account="7")).total == 0
    for selected in ([gone.id], [foreign.id], [a.id, foreign.id], [99999]):
        with pytest.raises(DomainError, match="Invalid area selection"):
            service.tracking(env.admin, window(area=selected))
    assert service.detail(env.admin, ids[2]).route == "gone"


@pytest.mark.integration
def test_status_exception_order_and_void_precedence(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    delivered, returned, incomplete, attempted, suppressed, void = [
        make(env, f"status-{i}") for i in range(6)
    ]
    for item in (delivered, returned, incomplete, void):
        update(env, item, deliver_time=NOW, pod_name="Signer")
        event(env, item, "delivered", NOW)
    update(env, incomplete, pod_name="   ")
    event(env, returned, "returned", NOW + timedelta(hours=1))
    # Late arrival with an older timestamp cannot change the terminal outcome.
    event(env, returned, "delivered", NOW - timedelta(hours=1))
    event(env, delivered, "returned", NOW - timedelta(hours=1))
    event(env, delivered, "attempted", NOW + timedelta(hours=2))
    event(env, attempted, "attempted", NOW + timedelta(days=20))
    event(env, suppressed, "attempted", NOW + timedelta(days=20))
    event(env, suppressed, "out for delivery", NOW + timedelta(days=21))
    update(env, void, deleted_at=NOW)
    event(env, void, "returned", NOW + timedelta(hours=1))
    service = QueryService(env.engine)
    result = service.tracking(env.admin, window())
    assert result.metrics.model_dump() == {
        "total": 6,
        "delivered": 1,
        "undelivered": 4,
        "void": 1,
        "otp": 100.0,
    }
    assert [
        row.id
        for row in service.tracking(env.admin, window(exception="attempted")).items
    ] == [str(attempted)]
    assert [
        row.id
        for row in service.tracking(env.admin, window(exception="returned")).items
    ] == [str(returned)]
    assert (
        service.tracking(env.admin, window(status="delivered", exception="void")).total
        == 0
    )
    assert service.tracking(env.admin, window(status="undelivered")).total == 4
    detail = service.detail(env.admin, returned)
    assert (
        detail.status == "Undelivered"
        and detail.deliver_time == NOW
        and detail.pod_name == "Signer"
    )
    assert service.detail(env.admin, incomplete).deliver_time == NOW
    assert service.detail(env.admin, void).status == "Void"
    # Equal-time terminal tie goes to last receipt; nonterminal does not undo it.
    event(env, returned, "delivered", NOW + timedelta(hours=1))
    assert service.detail(env.admin, returned).status == "Delivered"
    assert service.tracking(env.admin, window(exception="void")).metrics.otp == 0
    assert service.tracking(env.admin, window(account="nonexistent")).metrics.otp == 0


@pytest.mark.integration
def test_search_namespaces_history_and_stable_duplicate_detail(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    first = make(env, "00001")
    second = make(env, "000NUM")
    other = (
        ShipmentService(env.engine)
        .create(
            env.other,
            shipment_input(
                account_number="0008", reference="00001", shipment_number="000NUM"
            ),
        )
        .shipment
    )
    update(
        env,
        first,
        deleted_at=NOW,
        due_time=datetime(2000, 1, 1, tzinfo=UTC),
        due_date=date(2000, 1, 1),
    )
    service = QueryService(env.engine)
    assert service.search(env.admin, SearchQuery(identifier="000NUM")).items[
        0
    ].id == str(second)
    result = service.search(
        env.regular,
        SearchQuery(identifier=" 000NUM ", field="shipment_number", length=1),
    )
    assert result.total == 2 and result.items[0].id == str(first)
    page2 = service.search(
        env.admin,
        SearchQuery(identifier="000NUM", field="shipment_number", length=1, page=2),
    )
    assert page2.items[0].id == str(second)
    assert service.detail(env.admin, int(page2.items[0].id)).reference == "000NUM"
    assert service.search(env.admin, SearchQuery(identifier="00001")).total == 1
    for value in ("1", "000num", "000N", "%' OR 1=1 --"):
        assert (
            service.search(
                env.admin, SearchQuery(identifier=value, field="shipment_number")
            ).total
            == 0
        )
    for item in (int(other.id), 99999):
        with pytest.raises(DomainError, match="Shipment not found") as error:
            service.detail(env.admin, item)
        assert error.value.status == 404
    forged = env.admin.model_copy(update={"company": env.other.company})
    with pytest.raises(DomainError):
        service.search(forged, SearchQuery(identifier="00001"))
    with env.engine.begin() as connection:
        connection.execute(
            users.update().where(users.c.id == int(env.admin.id)).values(active=False)
        )
    with pytest.raises(DomainError):
        service.detail(env.admin, first)


@pytest.mark.integration
def test_detail_original_addresses_local_offsets_and_order(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    item = make(
        env,
        "local",
        reference_two="000SECOND",
        service_name="Description",
        package={"weight": "2.50"},
    )
    with env.engine.begin() as connection:
        validation = connection.execute(
            customers_validated.insert()
            .values(
                company_id=int(env.admin.company.id), timezone="America/Los_Angeles"
            )
            .returning(customers_validated.c.id)
        ).scalar_one()
        connection.execute(
            customers.update()
            .where(customers.c.company_id == int(env.admin.company.id))
            .values(validated_id=validation)
        )
    event(env, item, "attempted", datetime(2027, 1, 1, 17, tzinfo=UTC))
    event(env, item, "returned", datetime(2027, 1, 1, 17, tzinfo=UTC))
    event(env, item, "picked up", datetime(2026, 7, 1, 17, tzinfo=UTC))
    detail = QueryService(env.engine).detail(env.admin, item)
    assert detail.sender.address_one == detail.recipient.address_one == "1 Test Way"
    assert detail.recipient.zip == "00123" and detail.reference_two == "000SECOND"
    assert detail.service_name == "Description" and str(detail.weight) == "2.50"
    assert detail.pod_url is None
    assert [entry.action for entry in detail.history[:2]] == ["returned", "attempted"]
    history = detail.model_dump(mode="json")["history"]
    assert history[0]["event_time"].endswith("-08:00")
    assert next(entry for entry in history if entry["action"] == "picked up")[
        "event_time"
    ].endswith("-07:00")


@pytest.mark.integration
def test_query_http_contract_validation_security_and_errors(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    item = make(env, "00001")
    result = client.get(
        "/v1/shipments", params={"start_date": str(DAY), "end_date": str(DAY)}
    )
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert client.get("/v1/shipments?export=0").status_code == 200
    body = result.json()
    assert (
        isinstance(body["page"], int) and body["total"] == body["metrics"]["total"] == 1
    )
    assert body["items"][0]["due_time"].endswith("+00:00")
    found = client.get("/v1/shipments/search", params={"identifier": " 00001 "}).json()
    assert set(found["items"][0]) == {
        "id",
        "shipment_number",
        "reference",
        "route",
        "address_one",
        "city",
        "state",
        "zip",
    }
    detail = client.get(f"/v1/shipments/{item}")
    assert detail.status_code == 200 and detail.json()["recipient"]["zip"] == "00123"
    assert client.get("/v1/shipments/search?identifier=none").json()["total"] == 0
    foreign = (
        ShipmentService(env.engine)
        .create(env.other, shipment_input(account_number="0008", reference="hidden"))
        .shipment
    )
    assert client.get(f"/v1/shipments/{foreign.id}").status_code == 404
    assert client.get("/v1/shipments/search?identifier=hidden").json()["total"] == 0
    first_area, _ = AreaService(env.engine).create(env.admin, AreaInput(name="first"))
    second_area, _ = AreaService(env.engine).create(env.admin, AreaInput(name="second"))
    update(env, item, route=second_area.id)
    repeated = client.get(
        "/v1/shipments",
        params=[
            ("start_date", str(DAY)),
            ("end_date", str(DAY)),
            ("area", str(first_area.id)),
            ("area", str(second_area.id)),
        ],
    )
    assert repeated.status_code == 200 and repeated.json()["total"] == 1
    for query in (
        "start_date=2026-10-20",
        "page=0",
        "length=101",
        "date_type=wrong",
        "sort=private",
        "export=2",
        "area=0",
        "status=void",
        "company_id=1",
        "page=1&page=2",
        "account=0007&account=0008",
        "start_date=1792454400&end_date=2026-10-20",
    ):
        assert client.get(f"/v1/shipments?{query}").status_code == 422, query
    for path in (
        "/v1/shipments/search?identifier=x&field=both",
        "/v1/shipments/search?identifier=",
        f"/v1/shipments/{item}?company_id=1",
        "/v1/shipments/9223372036854775808",
    ):
        assert client.get(path).status_code == 422
    with env.engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(ingestion_errors)
            ).scalar_one()
            == 0
        )
    with patch.object(
        cast(FastAPI, client.app).state.queries,
        "tracking",
        side_effect=SQLAlchemyError("secret SQL"),
    ):
        response = client.get("/v1/shipments")
        assert response.status_code == 503 and response.json() == {
            "message": "Shipment queries are temporarily unavailable"
        }
    schema = client.get("/openapi.json").json()
    for path in (
        "/v1/shipments",
        "/v1/shipments/search",
        "/v1/shipments/{shipment_id}",
    ):
        assert schema["paths"][path]["get"]["security"]
    client.cookies.clear()
    for path in (
        "/v1/shipments",
        "/v1/shipments/search?identifier=00001",
        f"/v1/shipments/{item}",
    ):
        assert client.get(path).status_code == 401
