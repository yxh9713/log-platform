import base64
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.ingestion.cli import configure
from app.ingestion.worker import IntakeWorker
from app.pod.schema import shipment_images as images
from app.pod.storage import DummyPodStorage, PermanentStorageError
from app.pod.worker import PodWorker
from app.shipments.common import DomainError
from app.shipments.queries import QueryService
from app.shipments.schema import ingestion_errors, shipment_events, shipments
from app.shipments.service import ShipmentService
from tests.pod_support import image_input
from tests.shipment_support import CreationEnvironment, shipment_input
from tests.test_carriers import KEY, count, payload, prepare, row
from tests.test_intake import Crash
from tests.test_manifest_rules import csv_bytes

pytestmark = pytest.mark.integration


def all_images(env: CreationEnvironment) -> list[sa.RowMapping]:
    with env.engine.connect() as connection:
        return list(
            connection.execute(
                sa.select(images).order_by(images.c.created_at, images.c.id)
            ).mappings()
        )


def due(env: CreationEnvironment) -> None:
    with env.engine.begin() as connection:
        connection.execute(
            images.update().values(next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC))
        )


class FlakyStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = True

    def upload(self, object_key: str, data: bytes, content_type: str) -> str:
        self.calls.append((object_key, hashlib.sha256(data).hexdigest()))
        if self.fail:
            raise OSError("synthetic storage outage")
        return "https://pod.invalid/" + object_key


def test_valid_webhook_prepares_pending_then_dummy_ready_and_tenant_read(
    creation_client: tuple[TestClient, CreationEnvironment],
) -> None:
    client, env = creation_client
    _, integration = prepare(env)
    client.cookies.clear()
    response = client.post(
        f"/v1/webhook/{integration}",
        headers={"X-API-Key": KEY},
        json=payload(pod=image_input(), route="sfo"),
    )
    assert response.status_code == 200 and response.json()["outcome"] == "accepted"
    pending = all_images(env)[0]
    assert pending["state"] == "pending" and pending["url"] is None
    assert (pending["width"], pending["height"]) == (900, 450)
    assert len(pending["prepared_content"]) == pending["size_bytes"]
    assert (
        QueryService(env.engine).detail(env.admin, row(env)["id"]).status == "Delivered"
    )
    assert QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url is None
    PodWorker(env.engine).tick()
    ready = all_images(env)[0]
    assert ready["state"] == "ready" and ready["url"].startswith("https://pod.invalid/")
    assert ready["prepared_content"] is None and ready["attempts"] == 1
    assert (
        QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url
        == ready["url"]
    )
    with pytest.raises(DomainError) as error:
        QueryService(env.engine).detail(env.other, row(env)["id"])
    assert getattr(error.value, "status", None) == 404
    assert count(env, shipment_events) == 2 and count(env, images) == 1


def test_transient_failure_keeps_tracking_and_retries_same_prepared_content(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(
        integration, KEY, payload(pod=image_input("JPEG"), notes="accepted")
    )
    storage = FlakyStorage()
    worker = PodWorker(env.engine, storage)
    worker.tick()
    failed = all_images(env)[0]
    assert (
        failed["state"] == "retry_wait"
        and failed["attempts"] == 1
        and failed["prepared_content"]
    )
    assert (
        row(env)["deliver_time"]
        and row(env)["pod_name"] == "Test signer"
        and row(env)["notes"] == "accepted"
    )
    assert QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url is None
    worker.tick()
    assert len(storage.calls) == 1  # backoff is respected
    assert (
        service.receive(integration, KEY, payload(pod="changed invalid image"))[
            1
        ].outcome
        == "duplicate"
    )
    storage.fail = False
    due(env)
    worker.tick()
    assert all_images(env)[0]["state"] == "ready"
    assert len(storage.calls) == 2 and len(set(storage.calls)) == 1
    assert count(env, images) == 1 and count(env, shipment_events) == 2


def test_current_image_event_order_pending_failure_missing_and_return(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    first = all_images(env)[0]
    PodWorker(env.engine).run_image(first["id"])
    first_url = all_images(env)[0]["url"]
    service.receive(
        integration, KEY, payload(time="2098-10-29T17:00:00Z", pod=image_input("JPEG"))
    )
    second = all_images(env)[1]
    assert QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url is None
    service.receive(
        integration,
        KEY,
        payload(time="2098-10-28T17:00:00Z", pod=image_input(size=(30, 20))),
    )
    third = all_images(env)[2]
    PodWorker(env.engine).run_image(third["id"])
    assert QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url is None
    storage = FlakyStorage()
    PodWorker(env.engine, storage).run_image(second["id"])
    assert QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url is None
    storage.fail = False
    due(env)
    PodWorker(env.engine, storage).run_image(second["id"])
    selected = QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url
    assert selected and selected != first_url
    service.receive(integration, KEY, payload(time="2098-10-30T17:00:00Z", pod=""))
    service.receive(
        integration,
        KEY,
        payload(event="Returned", time="2098-10-31T17:00:00Z", pod=None),
    )
    detail = QueryService(env.engine).detail(env.admin, row(env)["id"])
    assert detail.pod_url == selected and detail.status == "Undelivered"
    assert count(env, images) == 3


def test_equal_event_time_image_receipt_ties_and_failed_latest_no_fallback(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    PodWorker(env.engine).tick()
    service.receive(
        integration, KEY, payload(event="Returned", pod=image_input("JPEG"))
    )
    latest = all_images(env)[1]

    class Permanent:
        def upload(self, object_key: str, data: bytes, content_type: str) -> str:
            raise PermanentStorageError("synthetic permanent failure")

    PodWorker(env.engine, Permanent()).run_image(latest["id"])
    assert all_images(env)[1]["state"] == "failed"
    assert QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url is None
    assert count(env, shipment_events) == 3 and count(env, images) == 2


@pytest.mark.parametrize("kind", ["unknown", "duplicate", "unmatched", "bad_account"])
def test_no_image_preparation_for_ignored_or_unauthorized_outcomes(
    creation_env: CreationEnvironment, kind: str
) -> None:
    env = creation_env
    service, integration = prepare(env)
    if kind == "duplicate":
        service.receive(integration, KEY, payload())
    value = payload(pod="not an image", route="new")
    if kind == "unknown":
        value["event"] = "unknown"
    if kind == "unmatched":
        value["reference"] = "missing"
    if kind == "bad_account":
        value["account"] = "wrong"
    with patch(
        "app.carriers.service.prepare",
        side_effect=AssertionError("Must not prepare image"),
    ):
        _, result, error = service.receive(integration, KEY, value)
    assert result.outcome in ("ignored", "duplicate", "rejected")
    assert count(env, images) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"pod": "not image"},
        {"pod": base64.b64encode(b"not jpeg/png").decode()},
        {"due_time": "bad"},
    ],
)
def test_invalid_image_or_deadline_rolls_back_whole_event(
    creation_env: CreationEnvironment, changes: dict[str, Any]
) -> None:
    env = creation_env
    service, integration = prepare(env)
    original = dict(row(env))
    _, result, error = service.receive(
        integration,
        KEY,
        payload(
            **{"pod": image_input(), "route": "new", "notes": "rollback", **changes}
        ),
    )
    assert result.outcome == "rejected" and error
    assert (
        dict(row(env)) == original
        and count(env, shipment_events) == 1
        and count(env, images) == 0
    )
    assert count(env, ingestion_errors) == 1


def test_bounded_storage_retries_private_cli_retry_and_no_event_replay(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    worker = PodWorker(env.engine, FlakyStorage())
    for _ in range(8):
        due(env)
        worker.tick()
    failed = all_images(env)[0]
    assert (
        failed["state"] == "failed"
        and failed["attempts"] == 5
        and failed["url"] is None
    )
    assert failed["prepared_content"] is not None
    with env.engine.connect() as connection:
        error = connection.execute(sa.select(ingestion_errors)).mappings().one()
        assert (
            error["image_id"] == failed["id"]
            and error["reason_code"] == "pod_storage_exhausted"
        )
    response = subprocess.run(
        [sys.executable, "-m", "app.pod.cli", "status"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(response.stdout)[0]["state"] == "failed"
    assert (
        "prepared_content" not in response.stdout
        and "Test signer" not in response.stdout
    )
    response = subprocess.run(
        [sys.executable, "-m", "app.pod.cli", "retry", "--image-id", failed["id"]],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(response.stdout) == {"image_retry_scheduled": True}
    PodWorker(env.engine).tick()
    assert (
        all_images(env)[0]["state"] == "ready" and all_images(env)[0]["attempts"] == 1
    )
    assert count(env, images) == 1 and count(env, shipment_events) == 2


def test_crash_after_upload_counts_attempt_and_reuses_object_key(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    calls: list[str] = []

    class Crashing:
        def upload(self, object_key: str, data: bytes, content_type: str) -> str:
            calls.append(object_key)
            raise Crash()

    with pytest.raises(Crash):
        PodWorker(env.engine, Crashing()).tick()
    image = all_images(env)[0]
    assert image["attempts"] == 1 and image["prepared_content"] and image["url"] is None
    due(env)

    class Recovery:
        def upload(self, object_key: str, data: bytes, content_type: str) -> str:
            calls.append(object_key)
            return DummyPodStorage().upload(object_key, data, content_type)

    PodWorker(env.engine, Recovery()).tick()
    assert (
        len(calls) == 2 and len(set(calls)) == 1 and all_images(env)[0]["attempts"] == 2
    )
    assert count(env, images) == 1 and count(env, shipment_events) == 2


def test_concurrent_image_workers_upload_once(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    storage = FlakyStorage()
    storage.fail = False
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: PodWorker(env.engine, storage).tick(), range(3)))
    assert len(storage.calls) == 1 and all_images(env)[0]["attempts"] == 1


def test_schema_prevents_cross_tenant_event_image_link(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    with env.engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            images.update().values(shipper_company_id=int(env.other.company.id))
        )
    ShipmentService(env.engine).create(env.admin, shipment_input(reference="other"))
    with env.engine.connect() as connection:
        other = connection.execute(
            sa.select(shipments.c.id).where(shipments.c.shipper_ref == "other")
        ).scalar_one()
    with env.engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(images.update().values(shipment_id=other))


def test_csv_image_rows_commit_partial_failures_and_pending_storage(
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
        "pod_image": image_input(),
        "sign": "CSV signer",
    }
    (folder / "pod.csv").write_bytes(
        csv_bytes(
            item,
            {**item, "timestamp": "10/28/2098 5:00:00 PM", "pod_image": "bad"},
            {
                **item,
                "timestamp": "10/29/2098 5:00:00 PM",
                "pod_image": image_input("JPEG"),
            },
        )
    )
    IntakeWorker(env.engine, tmp_path).tick(force=True)
    assert count(env, images) == 2 and count(env, shipment_events) == 3
    assert row(env)["pod_name"] == "CSV signer" and row(env)[
        "deliver_time"
    ] == datetime(2098, 10, 29, 17, tzinfo=UTC)
    assert all(image["state"] == "pending" for image in all_images(env))
    PodWorker(env.engine).tick()
    assert all(image["state"] == "ready" for image in all_images(env))


def test_late_older_completion_never_replaces_newer_ready_image(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    first = all_images(env)[0]
    service.receive(
        integration, KEY, payload(time="2098-10-28T17:00:00Z", pod=image_input("JPEG"))
    )
    second = all_images(env)[1]
    PodWorker(env.engine).run_image(second["id"])
    selected = QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url
    assert selected is not None
    PodWorker(env.engine).run_image(first["id"])
    assert (
        QueryService(env.engine).detail(env.admin, row(env)["id"]).pod_url == selected
    )


def test_ready_image_does_not_invent_missing_signer(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input(), sign=None))
    PodWorker(env.engine).tick()
    detail = QueryService(env.engine).detail(env.admin, row(env)["id"])
    assert (
        detail.pod_url
        and detail.deliver_time
        and detail.pod_name is None
        and detail.status == "Undelivered"
    )
    assert (
        service.receive(integration, KEY, payload(sign="late signer"))[1].outcome
        == "duplicate"
    )
    assert row(env)["pod_name"] is None
    service.receive(
        integration,
        KEY,
        payload(time="2098-10-28T17:00:00Z", sign="late signer", pod=None),
    )
    current = QueryService(env.engine).detail(env.admin, row(env)["id"])
    assert current.status == "Delivered" and current.pod_url == detail.pod_url


def test_database_checkpoint_failure_after_upload_preserves_retry(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    storage = FlakyStorage()
    storage.fail = False
    original_begin = env.engine.begin
    begins = 0

    def failing_begin() -> Any:
        nonlocal begins
        begins += 1
        if begins == 2:
            raise SQLAlchemyError("synthetic checkpoint outage")
        return original_begin()

    with (
        patch.object(env.engine, "begin", side_effect=failing_begin),
        pytest.raises(SQLAlchemyError),
    ):
        PodWorker(env.engine, storage).tick()
    pending = all_images(env)[0]
    assert (
        pending["attempts"] == 1
        and pending["prepared_content"]
        and pending["url"] is None
    )
    due(env)
    PodWorker(env.engine, storage).tick()
    assert all_images(env)[0]["state"] == "ready" and len(set(storage.calls)) == 1
    assert count(env, images) == 1 and count(env, shipment_events) == 2


@pytest.mark.parametrize("mode", ["checksum", "url", "exception"])
def test_storage_validation_and_exception_details_stay_private(
    creation_env: CreationEnvironment, mode: str
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))
    if mode == "checksum":
        image = all_images(env)[0]
        corrupt = (
            bytes([image["prepared_content"][0] ^ 1]) + image["prepared_content"][1:]
        )
        with env.engine.begin() as connection:
            connection.execute(images.update().values(prepared_content=corrupt))

    class BadStorage:
        def upload(self, object_key: str, data: bytes, content_type: str) -> str:
            if mode == "checksum":
                raise AssertionError("Checksum must fail before upload")
            if mode == "exception":
                raise RuntimeError("private provider failure")
            return "https://username:private-password@example.test/image"

    PodWorker(env.engine, BadStorage()).tick()
    image = all_images(env)[0]
    assert image["url"] is None and image["state"] == (
        "retry_wait" if mode == "exception" else "failed"
    )
    assert "private" not in str(image["reason_code"])
    with env.engine.connect() as connection:
        errors = (
            connection.execute(sa.select(ingestion_errors.c.reason_code))
            .scalars()
            .all()
        )
        assert all("private" not in code for code in errors)


def test_repeated_process_crashes_exhaust_durable_attempts(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    service, integration = prepare(env)
    service.receive(integration, KEY, payload(pod=image_input()))

    class Crashing:
        def upload(self, object_key: str, data: bytes, content_type: str) -> str:
            raise Crash()

    for _ in range(5):
        due(env)
        with pytest.raises(Crash):
            PodWorker(env.engine, Crashing()).tick()
    due(env)
    PodWorker(env.engine, Crashing()).tick()
    image = all_images(env)[0]
    assert image["state"] == "failed" and image["attempts"] == 5
    assert count(env, ingestion_errors) == 1 and count(env, shipment_events) == 2
