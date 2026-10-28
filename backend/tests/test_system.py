import base64
import csv
import hashlib
import io
from datetime import UTC, datetime, time
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from PIL import Image

from app.carriers.schema import integrations
from app.exports.service import ExportService
from app.exports.storage import open_download
from app.exports.worker import COLUMNS, ExportWorker
from app.ingestion.cli import configure
from app.ingestion.schema import ingestion_imports
from app.ingestion.worker import IntakeWorker
from app.ops.cli import diagnose
from app.pod.schema import shipment_images
from app.pod.storage import DummyPodStorage
from app.pod.worker import PodWorker
from app.shipments.queries import reporting_day
from app.shipments.query_dto import TrackingQuery
from app.shipments.schema import ingestion_errors, shipment_events, shipments
from tests.shipment_support import CreationEnvironment
from tests.test_carriers import KEY
from tests.test_intake import upload
from tests.test_manifest_rules import manifest_row

pytestmark = pytest.mark.integration


def test_manifest_carrier_pod_dashboard_export_recovery_pipeline(
    creation_client: tuple[TestClient, CreationEnvironment], tmp_path: Path
) -> None:
    client, env = creation_client
    with env.engine.connect() as c:
        day = reporting_day(c)
    due = datetime.combine(day, time(23), UTC)
    configure(env.engine, "paychex")
    upload(
        tmp_path,
        "paychex",
        "pipeline.csv",
        manifest_row(**{"Due Date/Time": due.isoformat()}),
        manifest_row(**{"Package ID": "rejected", "Due Date/Time": "bad"}),
    )
    intake = IntakeWorker(env.engine, tmp_path)
    intake.tick(force=True)
    with env.engine.begin() as c:
        job = c.execute(sa.select(ingestion_imports)).mappings().one()
        assert (
            job["state"] == "completed_with_errors"
            and job["rows_completed"] == job["rows_rejected"] == 1
        )
        assert (tmp_path / "paychex" / job["archive_path"]).is_file()
        identity = c.execute(sa.select(shipments.c.id)).scalar_one()
        integration = c.execute(
            integrations.insert()
            .values(
                company_id=env.carrier_id,
                apikey=hashlib.sha256(KEY.encode()).hexdigest(),
            )
            .returning(integrations.c.id)
        ).scalar_one()
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 600), "blue").save(buffer, format="PNG")
    body = {
        "event": "Delivered",
        "account": "0007",
        "reference": "00001",
        "time": datetime.combine(day, time(12), UTC).isoformat(),
        "sign": "Synthetic signer",
        "route": "Pipeline",
        "pod": base64.b64encode(buffer.getvalue()).decode(),
    }
    url = f"/v1/webhook/{integration}"
    assert client.post(url, json=body, headers={"X-API-Key": KEY}).status_code == 200
    with env.engine.connect() as c:
        image = c.execute(sa.select(shipment_images)).mappings().one()
        assert image["width"] == 900 and image["height"] == 450
        events = c.execute(
            sa.select(sa.func.count()).select_from(shipment_events)
        ).scalar_one()
    # An accepted duplicate cannot change signer, route, history or image work.
    assert (
        client.post(
            url,
            json={**body, "sign": "Changed", "route": "Ignored"},
            headers={"X-API-Key": KEY},
        ).status_code
        == 200
    )
    storage = DummyPodStorage()
    with patch.object(storage, "upload", side_effect=OSError("private storage path")):
        PodWorker(env.engine, storage).run_image(str(image["id"]))
    assert client.get(f"/v1/shipments/{identity}").json()["status"] == "Delivered"
    assert client.get(f"/v1/shipments/{identity}").json()["pod_url"] is None
    with env.engine.begin() as c:
        c.execute(shipment_images.update().values(next_attempt_at=sa.func.now()))
    PodWorker(env.engine).tick()
    detail = client.get(f"/v1/shipments/{identity}").json()
    assert (
        detail["pod_url"].startswith("https://pod.invalid/")
        and detail["pod_name"] == "Synthetic signer"
        and detail["route"] == "pipeline"
    )
    day_stats = client.get("/v1/my-day").json()
    assert day_stats["stats"] == {
        "total": 1,
        "delivered": 1,
        "undelivered": 0,
        "void": 0,
        "otp": 100.0,
    }
    assert day_stats["areas"][0]["total"] == 1
    exports = ExportService(env.engine)
    export = exports.accept(env.admin, TrackingQuery())
    worker = ExportWorker(env.engine, tmp_path / "download")
    with patch.object(worker, "generate", side_effect=OSError("private output path")):
        worker.run_job(export)
    assert exports.list(env.admin).items[0].url is None
    from app.exports.schema import jobs

    with env.engine.begin() as c:
        c.execute(jobs.update().values(next_attempt_at=sa.func.now()))
    worker.run_job(export)
    output = exports.get(env.admin, export)
    rows = list(
        csv.reader(
            io.StringIO(
                b"".join(
                    open_download(
                        tmp_path / "download",
                        export,
                        output["filename"],
                        output["size_bytes"],
                    )
                ).decode()
            )
        )
    )
    assert (
        rows[0] == list(COLUMNS)
        and rows[1][0] == "000NUMBER"
        and rows[1][2] == "pipeline"
        and rows[1][5] == "Synthetic signer"
    )
    assert not exports.list(env.regular).items and not exports.list(env.other).items
    upload(
        tmp_path,
        "paychex",
        "renamed-pipeline.csv",
        manifest_row(**{"Due Date/Time": due.isoformat()}),
        manifest_row(**{"Package ID": "rejected", "Due Date/Time": "bad"}),
    )
    intake.tick(force=True)
    with env.engine.connect() as c:
        assert (
            c.execute(sa.select(sa.func.count()).select_from(shipments)).scalar_one()
            == 1
        )
        assert (
            c.execute(
                sa.select(sa.func.count()).select_from(shipment_events)
            ).scalar_one()
            == events
        )
        assert (
            c.execute(
                sa.select(sa.func.count()).select_from(shipment_images)
            ).scalar_one()
            == 1
        )
    diagnostics = diagnose(env.engine)
    assert diagnostics["exports"]["states"] == {"ready": 1} and diagnostics["pod"][
        "states"
    ] == {"ready": 1}
    assert diagnostics["imports"]["states"] == {
        "completed_with_errors": 1,
        "skipped": 1,
    }
    assert (
        diagnostics["timezone"] == "UTC"
        and diagnostics["migration_head"] == "0007_exports"
    )
    assert "private" not in str(diagnostics) and "Synthetic signer" not in str(
        diagnostics
    )


def test_diagnostics_counts_without_rows_or_mutations(
    creation_env: CreationEnvironment,
) -> None:
    env = creation_env
    with env.engine.begin() as c:
        c.execute(
            ingestion_errors.insert().values(
                shipper_company_id=int(env.admin.company.id),
                source_type="system_test",
                reason_code="synthetic_failure",
                received_reference="PRIVATE-REFERENCE",
            )
        )
    before = diagnose(env.engine)
    after = diagnose(env.engine)
    assert (
        before["ingestion_errors_by_code"]
        == after["ingestion_errors_by_code"]
        == {"synthetic_failure": 1}
    )
    assert before["exports"]["due"] == 0 and before["pod"]["due"] == 0
    assert "PRIVATE-REFERENCE" not in str(before)


def test_system_setup_refuses_nonlab_database(
    creation_env: CreationEnvironment,
) -> None:
    from tests import system_setup

    with patch("tests.system_setup.command.upgrade") as upgrade:
        with pytest.raises(RuntimeError, match="isolated P12"):
            system_setup.main()
    upgrade.assert_not_called()
