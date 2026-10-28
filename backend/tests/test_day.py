from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db.schema import company, users
from app.shipments.accounts import AccountMappingService
from app.shipments.areas import AreaService
from app.shipments.common import DomainError
from app.shipments.day import DayService
from app.shipments.dto import AreaInput
from app.shipments.queries import metrics, reporting_day
from app.shipments.schema import ingestion_errors
from app.shipments.service import ShipmentService
from tests.shipment_support import CreationEnvironment, shipment_input
from tests.test_carriers import KEY, payload, prepare
from tests.test_queries import event, update

pytestmark = pytest.mark.integration


def today(env: CreationEnvironment) -> date:
    with env.engine.connect() as connection:
        return reporting_day(connection)


def make(env: CreationEnvironment, reference: str, day: date, **changes: Any) -> int:
    deadline = datetime.combine(day, time(17), UTC)
    package = (
        ShipmentService(env.engine)
        .create(
            env.admin,
            shipment_input(
                reference=reference, due_time=deadline.isoformat(), **changes
            ),
        )
        .shipment
    )
    # Created precedes source history, even when the fixture's source events are
    # intentionally older than the current UTC processing date.
    from app.shipments.schema import shipment_events

    with env.engine.begin() as connection:
        connection.execute(
            shipment_events.update()
            .where(shipment_events.c.shipment_id == int(package.id))
            .values(event_time=deadline - timedelta(days=10))
        )
    return int(package.id)


def test_day_matrix_and_active_area_reconciliation(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    day = today(env)
    at = datetime.combine(day, time(12), UTC)
    areas = AreaService(env.engine)
    a, _ = areas.create(env.admin, AreaInput(name="Alpha"))
    empty, _ = areas.create(env.admin, AreaInput(name="Empty"))
    void_area, _ = areas.create(env.admin, AreaInput(name="Void"))
    deleted, _ = areas.create(env.admin, AreaInput(name="Deleted"))
    areas.delete(env.admin, deleted.id)
    delivered = [make(env, f"delivered-{index}", day) for index in range(3)]
    for index, identity in enumerate(delivered):
        update(
            env,
            identity,
            route=a.id,
            deliver_time=at if index < 2 else at.replace(hour=17),
            pod_name="Signer",
        )
        event(env, identity, "delivered", at)
    attempted = make(env, "attempted", day)
    update(env, attempted, route=a.id)
    event(env, attempted, "attempted", at - timedelta(days=2))
    event(env, attempted, "attempted", at - timedelta(days=1))
    suppressed = make(env, "suppressed", day)
    update(env, suppressed, route=deleted.id)
    event(env, suppressed, "attempted", at - timedelta(days=1))
    event(env, suppressed, "out for delivery", at)
    returned = make(env, "returned", day)
    event(env, returned, "delivered", at - timedelta(days=2))
    event(env, returned, "returned", at - timedelta(days=1))
    update(
        env, returned, deliver_time=at - timedelta(days=2), pod_name="Retained signer"
    )
    voided = make(env, "void", day)
    update(
        env,
        voided,
        route=void_area.id,
        deleted_at=at,
        deliver_time=at,
        pod_name="Signer",
    )
    event(env, voided, "attempted", at)
    incomplete = make(env, "incomplete", day)
    update(env, incomplete, route=a.id, deliver_time=at)
    event(env, incomplete, "delivered", at)
    make(env, "tomorrow", day + timedelta(days=1))
    make(env, "yesterday", day - timedelta(days=1))
    other = (
        ShipmentService(env.engine)
        .create(
            env.other,
            shipment_input(
                reference="same-tenant-ref",
                account_number="0008",
                due_time=at.isoformat(),
            ),
        )
        .shipment
    )
    other_area, _ = areas.create(env.other, AreaInput(name="alpha"))
    update(env, int(other.id), route=other_area.id)
    report = DayService(env.engine).my_day(env.regular)
    assert report.report_date == day
    assert report.stats.model_dump() == {
        "total": 8,
        "delivered": 3,
        "undelivered": 4,
        "void": 1,
        "otp": 66.67,
    }
    assert report.exceptions.model_dump() == {
        "attempted": 1,
        "returned": 1,
        "void": 1,
        "consolidated": 0,
        "no_package": 0,
        "held": 0,
    }
    assert [item.area for item in report.areas] == ["alpha", "empty", "void"]
    alpha, zero, all_void = report.areas
    assert (
        alpha.total == 5
        and alpha.delivered == 3
        and alpha.undelivered == 2
        and alpha.otp == 66.67
    )
    assert zero.id == empty.id and zero.total == 0 and zero.otp == 0
    assert all_void.total == all_void.void == 1 and all_void.otp == 0
    assert sum(item.total for item in report.areas) == 6 < report.stats.total
    other_report = DayService(env.engine).my_day(env.other)
    assert other_report.stats.total == 1 and len(other_report.areas) == 1
    assert (
        other_report.areas[0].id == other_area.id and other_report.areas[0].total == 1
    )


@pytest.mark.parametrize("kind", ["empty", "undelivered", "void", "incomplete"])
def test_zero_and_no_delivery_otp_cases(
    creation_env: CreationEnvironment, kind: str
) -> None:
    env = creation_env
    day = today(env)
    saved, _ = AreaService(env.engine).create(env.admin, AreaInput(name="empty"))
    if kind != "empty":
        identity = make(env, kind, day)
        update(
            env,
            identity,
            route=saved.id,
            **(
                {"deleted_at": datetime.now(UTC)}
                if kind == "void"
                else {"deliver_time": datetime.now(UTC)}
                if kind == "incomplete"
                else {}
            ),
        )
    result = DayService(env.engine).my_day(env.admin)
    assert result.stats.otp == (0 if kind in ("empty", "void") else 100)
    assert result.areas[0].otp == result.stats.otp


def test_latest_action_all_history_ties_and_current_delivered_exclusion(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    day = today(env)
    at = datetime.combine(day, time(12), UTC)
    same = make(env, "tie", day)
    event(env, same, "attempted", at)
    event(env, same, "possession", at)
    repeat = make(env, "repeat", day)
    event(env, repeat, "attempted", at)
    event(env, repeat, "attempted", at + timedelta(seconds=1))
    current = make(env, "delivered", day)
    event(env, current, "delivered", at)
    event(env, current, "attempted", at + timedelta(seconds=1))
    update(env, current, deliver_time=at, pod_name="Signer")
    old = make(env, "old", day)
    event(env, old, "returned", at - timedelta(days=1))
    result = DayService(env.engine).my_day(env.admin)
    assert result.exceptions.attempted == 1 and result.exceptions.returned == 1
    assert result.stats.delivered == 1 and result.stats.otp == 100


def test_database_utc_day_not_connection_timezone(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    with env.engine.begin() as connection:
        utc = connection.execute(
            sa.select(sa.func.timezone("UTC", sa.func.now()))
        ).scalar_one()
        zone = "Pacific/Honolulu" if utc.hour < 10 else "Pacific/Kiritimati"
        connection.execute(
            sa.text("SELECT set_config('timezone',:zone,true)"), {"zone": zone}
        )
        assert (
            connection.execute(sa.select(sa.func.current_date())).scalar_one()
            != utc.date()
        )
        assert reporting_day(connection) == utc.date()


def test_due_day_defaults_independent_of_order_and_delivery_dates(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    day = today(env)
    first = make(env, "due-today", day)
    update(
        env,
        first,
        order_date=day - timedelta(days=10),
        deliver_time=datetime.combine(day - timedelta(days=1), time(12), UTC),
        pod_name="Signer",
    )
    second = make(env, "due-tomorrow", day + timedelta(days=1))
    update(
        env,
        second,
        order_date=day,
        deliver_time=datetime.combine(day, time(12), UTC),
        pod_name="Signer",
    )
    assert DayService(env.engine).my_day(env.admin).stats.total == 1


def test_same_snapshot_across_global_exceptions_and_area_counts(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    day = today(env)
    saved, _ = AreaService(env.engine).create(env.admin, AreaInput(name="sfo"))
    identity = make(env, "snapshot", day)
    update(env, identity, route=saved.id)

    def move_after_global(*args: Any) -> Any:
        value = metrics(*args)
        update(
            env,
            identity,
            due_date=day + timedelta(days=1),
            due_time=datetime.combine(day + timedelta(days=1), time(17), UTC),
        )
        return value

    with patch("app.shipments.day.metrics", side_effect=move_after_global):
        report = DayService(env.engine).my_day(env.admin)
    assert report.stats.total == report.areas[0].total == 1
    assert DayService(env.engine).my_day(env.admin).stats.total == 0


def test_area_rename_delete_restore_and_shared_role_reads(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    day = today(env)
    service = AreaService(env.engine)
    saved, _ = service.create(env.admin, AreaInput(name="west"))
    identity = make(env, "in-area", day)
    update(env, identity, route=saved.id)
    service.rename(env.admin, saved.id, AreaInput(name="east"))
    assert DayService(env.engine).my_day(env.regular).areas[0].area == "east"
    service.delete(env.admin, saved.id)
    report = DayService(env.engine).my_day(env.admin)
    assert report.stats.total == 1 and report.areas == []
    restored, _ = service.create(env.admin, AreaInput(name="east"))
    assert (
        restored.id == saved.id
        and DayService(env.engine).my_day(env.regular).areas[0].total == 1
    )


def test_carrier_corrections_refresh_metrics_and_duplicates_do_not(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    day = today(env)
    at = datetime.combine(day, time(12), UTC)
    carrier, integration = prepare(env)
    identity = make(env, "day-carrier", day)
    base = payload(
        reference="day-carrier", time=at.isoformat(), sign="Signer", route="sfo"
    )
    carrier.receive(integration, KEY, base)
    report = DayService(env.engine).my_day(env.admin)
    assert report.stats.delivered == 1 and report.stats.otp == 100
    carrier.receive(integration, KEY, {**base, "due_time": at.isoformat()})
    assert DayService(env.engine).my_day(env.admin).stats.otp == 100
    carrier.receive(
        integration,
        KEY,
        {
            **base,
            "event": "Possession",
            "time": (at + timedelta(seconds=1)).isoformat(),
            "due_time": at.isoformat(),
        },
    )
    assert DayService(env.engine).my_day(env.admin).stats.otp == 0
    carrier.receive(
        integration,
        KEY,
        {**base, "event": "Returned", "time": (at + timedelta(seconds=2)).isoformat()},
    )
    assert DayService(env.engine).my_day(env.admin).stats.undelivered >= 1 and identity


@pytest.mark.parametrize(
    "path", ["shipment-stats", "exceptions-stats", "area-stats", "my-day"]
)
def test_statistics_api_contract_auth_queries_and_failures(
    creation_client: tuple[TestClient, CreationEnvironment], path: str
) -> None:
    client, env = creation_client
    response = client.get("/v1/" + path)
    assert (
        response.status_code == 200 and response.headers["cache-control"] == "no-store"
    )
    assert response.json()["report_date"] == today(env).isoformat()
    assert "currentHour" not in response.text
    assert (
        client.get(
            "/v1/" + path + "?shipper_company_id=" + env.other.company.id
        ).status_code
        == 422
    )
    assert client.get("/v1/" + path + "?start_date=2026-01-01").status_code == 422
    assert count_errors(env) == 0
    with patch.object(
        cast(FastAPI, client.app).state.day,
        "my_day",
        side_effect=SQLAlchemyError("private query failure"),
    ):
        response = client.get("/v1/" + path)
    assert response.status_code == 503 and "private" not in response.text
    client.cookies.clear()
    assert client.get("/v1/" + path).status_code == 401


def count_errors(env: CreationEnvironment) -> int:
    with env.engine.connect() as connection:
        return int(
            connection.execute(
                sa.select(sa.func.count()).select_from(ingestion_errors)
            ).scalar_one()
        )


def test_forged_and_disabled_memberships_cannot_read_statistics(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    forged = env.admin.model_copy(update={"company": env.other.company})
    with pytest.raises(DomainError):
        DayService(env.engine).my_day(forged)
    with env.engine.begin() as connection:
        connection.execute(
            users.update().where(users.c.id == int(env.admin.id)).values(active=False)
        )
    with pytest.raises(DomainError):
        DayService(env.engine).my_day(env.admin)


def test_one_shipper_population_spans_all_assigned_carriers(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    day = today(env)
    make(env, "first-carrier", day)
    with env.engine.begin() as connection:
        carrier = connection.execute(
            company.insert()
            .values(
                name="Second test carrier", slug="second-test-carrier", company_type=1
            )
            .returning(company.c.id)
        ).scalar_one()
    AccountMappingService(env.engine).configure(
        int(env.admin.company.id), carrier, "SECOND.SERVICE", "0007"
    )
    make(env, "second-carrier", day, carrier_id="SECOND.SERVICE")
    result = DayService(env.engine).my_day(env.admin)
    assert (
        result.stats.total == result.stats.undelivered == 2 and result.stats.otp == 100
    )
