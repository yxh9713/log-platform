import asyncio
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.requests import Request

from app.auth.service import InvalidSession
from app.db.schema import users
from app.exports.dto import ExportList
from app.exports.routes import stream
from app.exports.schema import jobs
from app.exports.service import ExportService
from app.exports.storage import artifact, open_download
from app.exports.worker import COLUMNS, ExportWorker, csv_cell
from app.shipments.areas import AreaService
from app.shipments.common import DomainError
from app.shipments.dto import AreaInput
from app.shipments.queries import QueryService, reporting_day
from app.shipments.query_dto import TrackingQuery
from app.shipments.schema import shipments
from app.shipments.service import ShipmentService
from tests.shipment_support import CreationEnvironment, shipment_input
from tests.test_queries import event, update


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (0, "0"),
        ("0007", "0007"),
        ("=1+1", "'=1+1"),
        ("  @SUM(A1)", "'  @SUM(A1)"),
        ("\tdata", "'\tdata"),
        ('text,\n"quoted"', 'text,\n"quoted"'),
    ],
)
def test_csv_safety_preserves_truth(value: object, expected: str) -> None:
    assert csv_cell(value) == expected


@pytest.mark.parametrize(
    "filename", ["../outside.csv", "shipment-2026-01-01.csv/other", "evil.csv"]
)
def test_artifact_names_are_fixed(tmp_path: Path, filename: str) -> None:
    with pytest.raises(ValueError):
        artifact(tmp_path, str(uuid4()), filename)


def package(env: CreationEnvironment, ref: str, **changes: Any) -> int:
    with env.engine.connect() as connection:
        day = reporting_day(connection)
    changes.setdefault(
        "due_time", datetime(day.year, day.month, day.day, 17, tzinfo=UTC).isoformat()
    )
    return int(
        ShipmentService(env.engine)
        .create(env.admin, shipment_input(reference=ref, **changes))
        .shipment.id
    )


def run(
    env: CreationEnvironment, root: Path, query: TrackingQuery | None = None
) -> tuple[str, list[list[str]]]:
    service = ExportService(env.engine)
    identity = service.accept(env.admin, query or TrackingQuery(export=1))
    ExportWorker(env.engine, root).run_job(identity)
    job = service.get(env.admin, identity)
    assert job["state"] == "ready"
    data = b"".join(open_download(root, identity, job["filename"], job["size_bytes"]))
    return identity, list(csv.reader(io.StringIO(data.decode())))


integration = pytest.mark.integration


@integration
def test_all_rows_not_page_exact_columns_and_cells(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    route, _ = AreaService(env.engine).create(env.admin, AreaInput(name="Old route"))
    for index in range(13):
        identity = package(env, f"{index:04}", shipment_number="000" + str(index))
        update(
            env,
            identity,
            route=route.id if index < 10 else None,
            pod_name='Name, "Quoted"\nNext' if index == 0 else None,
            order_date=date(2026, 1, 1) if index == 0 else None,
        )
    # Deleted-area enrichment and NULL route do not drop rows.
    AreaService(env.engine).delete(env.admin, route.id)
    ShipmentService(env.engine).create(
        env.other, shipment_input(reference="foreign", account_number="0008")
    )
    job_id, rows = run(env, tmp_path, TrackingQuery(export=1, page=99, length=1))
    assert rows[0] == list(COLUMNS) and len(rows) == 14
    assert rows[1][:4] == ["0000", "OnTrac", "old route", "2026-01-01"]
    assert rows[1][5] == 'Name, "Quoted"\nNext' and rows[1][6] == ""
    assert rows[-1][2] == "" and rows[-1][3] == ""
    assert ExportService(env.engine).get(env.admin, job_id)["row_count"] == 13


@integration
@pytest.mark.parametrize(
    "changes",
    [
        dict(account="0007"),
        dict(status="delivered"),
        dict(status="undelivered"),
        dict(exception="attempted"),
        dict(exception="returned"),
        dict(exception="void"),
        dict(status="delivered", exception="void"),
    ],
)
def test_export_matches_list_predicates(
    creation_env: CreationEnvironment, tmp_path: Path, changes: dict[str, str]
) -> None:
    env = creation_env
    at = datetime.now(UTC)
    for index in range(4):
        identity = package(env, f"case{index}", shipment_number=f"000{index}")
        if index == 0:
            update(env, identity, pod_name="Signer", deliver_time=at)
            event(env, identity, "delivered", at)
        if index == 1:
            event(env, identity, "attempted", at + timedelta(minutes=1))
        if index == 2:
            event(env, identity, "returned", at + timedelta(minutes=2))
        if index == 3:
            update(env, identity, deleted_at=at)
    query = TrackingQuery.model_validate(changes)
    expected = QueryService(env.engine).tracking(env.admin, query)
    _, rows = run(env, tmp_path, query)
    assert {row[0] for row in rows[1:]} == {
        row.shipment_number for row in expected.items
    }
    assert len(rows) - 1 == expected.total


@integration
def test_accepted_dates_frozen_worker_reads_later_rows_and_deleted_selection(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    route, _ = AreaService(env.engine).create(env.admin, AreaInput(name="North"))
    with env.engine.connect() as connection:
        today = reporting_day(connection)
    identity = service.accept(env.admin, TrackingQuery(area=[route.id], export=1))
    saved = service.get(env.admin, identity)["filters"]
    assert saved["start_date"] == saved["end_date"] == today.isoformat()
    first = package(env, "after-accept", shipment_number="NEW")
    update(env, first, route=route.id)
    package(env, "not-selected", shipment_number="NO")
    AreaService(env.engine).delete(env.admin, route.id)
    with patch(
        "app.exports.worker.reporting_day", return_value=today + timedelta(days=1)
    ):
        ExportWorker(env.engine, tmp_path).run_job(identity)
    job = service.get(env.admin, identity)
    assert job["state"] == "ready" and job["row_count"] == 1
    assert job["filename"] == f"shipment-{today + timedelta(days=1)}.csv"
    with pytest.raises(DomainError):
        service.accept(env.admin, TrackingQuery(area=[route.id]))


@integration
def test_area_or_explicit_dates_timezone_and_formula(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    areas = AreaService(env.engine)
    a, _ = areas.create(env.admin, AreaInput(name="a"))
    b, _ = areas.create(env.admin, AreaInput(name="b"))
    for index, route in enumerate((a.id, b.id, None)):
        identity = package(
            env,
            str(index),
            shipment_number='=HYPERLINK("bad")' if index == 0 else "0000",
        )
        update(
            env,
            identity,
            route=route,
            order_date=date(2020, 1, 1),
            deliver_time=datetime(2020, 1, 2, 3, 4, tzinfo=UTC),
        )
    query = TrackingQuery(
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 1),
        date_type="order_date",
        area=[a.id, b.id],
    )
    _, rows = run(env, tmp_path, query)
    assert len(rows) == 3 and rows[1][0].startswith("'=") and rows[2][0] == "0000"
    assert rows[1][-1] == "2020-01-02T03:04:00+00:00"
    with env.engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(shipments.c.shipment_number).where(
                    shipments.c.shipper_ref == "0"
                )
            )
            .scalar_one()
            .startswith("=")
        )


@integration
def test_requester_tenant_disabled_and_fk_isolation(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    identity, _ = run(env, tmp_path)
    assert not service.list(env.regular).items and not service.list(env.other).items
    for principal in (env.regular, env.other):
        with pytest.raises(DomainError) as denied:
            service.get(principal, identity)
        assert denied.value.status == 404
        with pytest.raises(DomainError):
            service.dismiss(principal, identity)
    with env.engine.begin() as connection:
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                jobs.insert().values(
                    id=str(uuid4()),
                    requester_id=int(env.admin.id),
                    company_id=int(env.other.company.id),
                    filters={},
                )
            )
        connection.execute(
            users.update().where(users.c.id == int(env.admin.id)).values(active=False)
        )
    with pytest.raises(DomainError):
        service.get(env.admin, identity)


@integration
def test_retries_exhaustion_empty_output_and_no_false_ready(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    identity = service.accept(env.admin, TrackingQuery())
    worker = ExportWorker(env.engine, tmp_path)
    with patch.object(worker, "generate", side_effect=OSError("private path failure")):
        for attempt in range(1, 6):
            worker.run_job(identity)
            job = service.get(env.admin, identity)
            assert job["attempts"] == attempt and job["filename"] is None
            assert service.list(env.admin).items[0].url is None
            worker.run_job(identity)
            assert service.get(env.admin, identity)["attempts"] == attempt
            with env.engine.begin() as connection:
                connection.execute(
                    jobs.update()
                    .where(jobs.c.id == identity)
                    .values(next_attempt_at=sa.func.now())
                )
    assert service.get(env.admin, identity)["state"] == "failed"
    service.dismiss(env.admin, identity)
    service.dismiss(env.admin, identity)
    assert not service.list(env.admin).items
    second, rows = run(env, tmp_path)
    assert rows == [list(COLUMNS)] and service.get(env.admin, second)["row_count"] == 0


@integration
def test_concurrent_workers_ready_idempotence_and_storage_failure(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    package(env, "concurrency")
    identity = service.accept(env.admin, TrackingQuery())
    worker = ExportWorker(env.engine, tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker.run_job, [identity, identity]))
    job = service.get(env.admin, identity)
    assert job["state"] == "ready" and job["attempts"] == 1
    file = artifact(tmp_path, identity, job["filename"])
    before = file.read_bytes()
    modified = file.stat().st_mtime_ns
    worker.run_job(identity)
    assert file.read_bytes() == before and file.stat().st_mtime_ns == modified
    file.unlink()
    with pytest.raises(DomainError) as missing:
        open_download(tmp_path, identity, job["filename"], job["size_bytes"])
    assert missing.value.status == 503
    assert service.get(env.admin, identity)["state"] == "ready"


@integration
def test_crash_after_file_before_ready_recovers_without_notifications_regenerating(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    identity = service.accept(env.admin, TrackingQuery())
    worker = ExportWorker(env.engine, tmp_path)
    real = worker.generate

    def crash(job: sa.RowMapping) -> tuple[str, int, int, str]:
        real(job)
        raise RuntimeError("process interrupted")

    with (
        patch.object(worker, "generate", side_effect=crash),
        pytest.raises(RuntimeError),
    ):
        worker.run_job(identity)
    assert service.get(env.admin, identity)["state"] == "retry_wait"
    with env.engine.begin() as connection:
        connection.execute(
            jobs.update()
            .where(jobs.c.id == identity)
            .values(next_attempt_at=sa.func.now())
        )
    worker.run_job(identity)
    assert service.get(env.admin, identity)["state"] == "ready"
    with patch.object(
        worker, "generate", side_effect=AssertionError("ready job regenerated")
    ):
        service.list(env.admin)
        service.list(env.admin)
        worker.run_job(identity)


@integration
def test_acceptance_limit_is_concurrent_and_completed_dismiss_frees_slot(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    with patch("app.exports.service.MAX_OUTSTANDING", 2):
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(
                pool.map(lambda _: service.accept(env.admin, TrackingQuery()), range(2))
            )
        with pytest.raises(DomainError) as limited:
            service.accept(env.admin, TrackingQuery())
        assert limited.value.status == 429
        with pytest.raises(DomainError):
            service.dismiss(env.admin, ids[0])
        ExportWorker(env.engine, tmp_path).run_job(ids[0])
        service.dismiss(env.admin, ids[0])
        service.accept(env.admin, TrackingQuery())


@integration
def test_disabled_requester_fails_before_generation(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    identity = service.accept(env.admin, TrackingQuery())
    with env.engine.begin() as connection:
        connection.execute(
            users.update().where(users.c.id == int(env.admin.id)).values(active=False)
        )
    ExportWorker(env.engine, tmp_path).run_job(identity)
    with env.engine.connect() as connection:
        row = (
            connection.execute(sa.select(jobs).where(jobs.c.id == identity))
            .mappings()
            .one()
        )
        assert (
            row["state"] == "failed"
            and row["reason_code"] == "export_unauthorized"
            and row["filename"] is None
        )
    assert not list(tmp_path.iterdir())


@integration
def test_api_acknowledgment_download_recovery_and_csrf(
    creation_client: tuple[TestClient, CreationEnvironment], tmp_path: Path
) -> None:
    client, env = creation_client
    app = cast(FastAPI, client.app)
    app.state.config.export_root = tmp_path
    assert client.get("/v1/shipments?export=1").status_code == 403
    headers = {"X-Requested-With": "logistics-web"}
    for query in ("page=1", "length=10", "export=1", "company_id=1"):
        assert (
            client.get("/v1/shipments?export=1&" + query, headers=headers).status_code
            == 422
        )
    assert (
        client.get(
            "/v1/shipments?export=1", headers={**headers, "Origin": "https://bad.test"}
        ).status_code
        == 403
    )
    response = client.get("/v1/shipments?export=1", headers=headers)
    assert (
        response.status_code == 202
        and response.json() == {"message": "we start to process data"}
        and response.headers["cache-control"] == "no-store"
    )
    item = client.get("/v1/exports").json()["items"][0]
    identity = item["id"]
    assert item["state"] == "pending" and item["url"] is None
    assert client.get(f"/v1/exports/{identity}/download").status_code == 409
    assert client.post(f"/v1/exports/{identity}/dismiss").status_code == 403
    ExportWorker(env.engine, tmp_path).run_job(identity)
    item = client.get(f"/v1/exports/{identity}").json()
    response = client.get(item["url"])
    assert response.status_code == 200 and response.text.strip() == ",".join(COLUMNS)
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="shipment-'
    )
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/v1/exports?company_id=1").status_code == 422
    assert (
        client.post(f"/v1/exports/{identity}/dismiss", headers=headers).status_code
        == 200
    )
    assert client.get("/v1/exports").json() == {"items": []}
    assert (
        client.get(
            "/v1/exports/events", headers={"Origin": "https://bad.test"}
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert client.get(item["url"]).status_code == 401
    assert client.get("/v1/exports/events").status_code == 401


@integration
def test_api_unavailable_is_sanitized_and_does_not_accept(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    app = cast(FastAPI, client.app)
    with patch.object(
        app.state.exports, "accept", side_effect=SQLAlchemyError("private sql")
    ):
        response = client.get(
            "/v1/shipments?export=1", headers={"X-Requested-With": "logistics-web"}
        )
    assert response.status_code == 503 and "private" not in response.text
    assert not ExportService(env.engine).list(env.admin).items


def test_sse_snapshot_replay_heartbeat_outage_and_revocation() -> None:
    class Auth:
        def authenticate(self, token: str) -> Any:
            return object()

    class Service:
        def list(self, principal: object) -> ExportList:
            return ExportList(items=[])

    app = FastAPI()
    app.state.auth = Auth()
    app.state.exports = Service()

    async def receive() -> Any:
        return {"type": "http.request", "body": b""}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/exports/events",
            "headers": [],
            "app": app,
        },
        receive,
    )

    async def check() -> None:
        async def sleep(seconds: int) -> None:
            return None

        with patch("app.exports.routes.asyncio.sleep", sleep):
            generator = stream(request, "synthetic")
            assert await anext(generator) == "retry: 3000\n\n"
            assert "event: exports" in await anext(generator)
            assert await anext(generator) == "event: heartbeat\ndata: {}\n\n"
            await generator.aclose()
            # A new stream always replays durable state, independent of Redis/cursor.
            generator = stream(request, "synthetic")
            await anext(generator)
            assert "event: exports" in await anext(generator)
            with patch.object(
                app.state.auth, "authenticate", side_effect=InvalidSession
            ):
                assert "session-expired" in await anext(generator)
                with pytest.raises(StopAsyncIteration):
                    await anext(generator)
            generator = stream(request, "synthetic")
            await anext(generator)
            with patch.object(
                app.state.exports, "list", side_effect=SQLAlchemyError("secret")
            ):
                assert await anext(generator) == "event: unavailable\ndata: {}\n\n"
            await generator.aclose()

    asyncio.run(check())


@integration
def test_streams_beyond_one_batch_with_actual_csv(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    for index in range(501):
        package(env, f"batch-{index}", shipment_number=f"{index:06}")
    pulses: list[int] = []
    service = ExportService(env.engine)
    identity = service.accept(env.admin, TrackingQuery(length=1))
    worker = ExportWorker(env.engine, tmp_path, lambda: pulses.append(1))
    worker.run_job(identity)
    job = service.get(env.admin, identity)
    data = b"".join(
        open_download(tmp_path, identity, job["filename"], job["size_bytes"])
    )
    rows = list(csv.reader(io.StringIO(data.decode())))
    assert len(rows) == 502 and rows[1][0] == "000000" and rows[-1][0] == "000500"
    assert job["row_count"] == 501 and pulses


@integration
def test_file_limit_and_symlink_never_publish_ready(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    package(env, "limit")
    identity = service.accept(env.admin, TrackingQuery())
    with patch("app.exports.worker.MAX_BYTES", 1):
        ExportWorker(env.engine, tmp_path).run_job(identity)
    assert service.get(env.admin, identity)["state"] == "failed"
    assert service.get(env.admin, identity)["reason_code"] == "export_too_large"
    assert not list(tmp_path.rglob("*.csv")) and not list(tmp_path.rglob(".part-*"))
    second = service.accept(env.admin, TrackingQuery())
    (tmp_path / second).symlink_to(tmp_path, target_is_directory=True)
    ExportWorker(env.engine, tmp_path).run_job(second)
    assert service.get(env.admin, second)["state"] == "failed"


@integration
def test_process_crashes_count_toward_attempt_bound(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    service = ExportService(env.engine)
    identity = service.accept(env.admin, TrackingQuery())
    worker = ExportWorker(env.engine, tmp_path)
    with patch.object(worker, "generate", side_effect=RuntimeError("crash")):
        for _attempt in range(5):
            with pytest.raises(RuntimeError):
                worker.run_job(identity)
            with env.engine.begin() as connection:
                connection.execute(
                    jobs.update()
                    .where(jobs.c.id == identity)
                    .values(next_attempt_at=sa.func.now())
                )
        worker.run_job(identity)
    assert service.get(env.admin, identity)["state"] == "failed"
    assert service.get(env.admin, identity)["attempts"] == 5


@integration
def test_live_sse_state_is_requester_scoped_and_recovers_ready(
    creation_client: tuple[TestClient, CreationEnvironment], tmp_path: Path
) -> None:
    client, env = creation_client
    app = cast(FastAPI, client.app)
    service = ExportService(env.engine)
    mine = service.accept(env.admin, TrackingQuery())
    theirs = service.accept(env.regular, TrackingQuery())
    ExportWorker(env.engine, tmp_path).tick()

    async def receive() -> Any:
        return {"type": "http.request", "body": b""}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/exports/events",
            "headers": [],
            "app": app,
        },
        receive,
    )

    async def check() -> None:
        generator = stream(request, client.cookies.get("logistics_session") or "")
        await anext(generator)
        message = await anext(generator)
        assert (
            mine in message and theirs not in message and '"state":"ready"' in message
        )
        await generator.aclose()

    asyncio.run(check())

    async def finite(request: Request, token: str) -> Any:
        yield 'event: exports\ndata: {"items":[]}\n\n'

    with patch("app.exports.routes.stream", finite):
        response = client.get("/v1/exports/events")
    assert response.status_code == 200 and response.headers["content-type"].startswith(
        "text/event-stream"
    )
    assert (
        response.headers["cache-control"] == "no-store"
        and response.headers["x-accel-buffering"] == "no"
    )
