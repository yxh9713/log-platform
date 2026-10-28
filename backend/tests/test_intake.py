import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app.ingestion import files
from app.ingestion.cli import configure
from app.ingestion.schema import (
    ingestion_imports as imports,
)
from app.ingestion.schema import (
    ingestion_rows as rows,
)
from app.ingestion.schema import (
    ingestion_source as sources,
)
from app.ingestion.worker import IntakeWorker
from app.shipments.accounts import AccountMappingService
from app.shipments.common import DomainError
from app.shipments.schema import customers, ingestion_errors, shipment_events, shipments
from app.shipments.service import ShipmentService
from tests.shipment_support import CreationEnvironment, shipment_input
from tests.test_manifest_rules import csv_bytes, manifest_row

pytestmark = pytest.mark.integration


def upload(root: Path, slug: str, name: str, *values: dict[str, str]) -> Path:
    folder = root / slug / "upload"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(csv_bytes(*values))
    return path


def records(env: CreationEnvironment) -> list[sa.RowMapping]:
    with env.engine.connect() as connection:
        return list(
            connection.execute(
                sa.select(imports).order_by(imports.c.received_at, imports.c.id)
            ).mappings()
        )


def make_due(env: CreationEnvironment) -> None:
    with env.engine.begin() as connection:
        connection.execute(
            imports.update().values(
                next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC),
                archive_next_at=datetime(2000, 1, 1, tzinfo=UTC),
            )
        )


def shipment_rows(env: CreationEnvironment) -> list[sa.RowMapping]:
    with env.engine.connect() as connection:
        return list(
            connection.execute(sa.select(shipments).order_by(shipments.c.id)).mappings()
        )


def test_finalization_mapping_dates_defaults_and_content_dedupe(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    pending = upload(tmp_path, "paychex", "mainfest-20261021.part", manifest_row())
    worker = IntakeWorker(env.engine, tmp_path)
    worker.tick(force=True)
    assert records(env) == []
    pending.rename(pending.with_suffix(".csv"))
    worker.tick(force=True)
    first = records(env)[0]
    assert first["state"] == "completed" and first["archive_state"] == "completed"
    assert first["rows_completed"] == first["rows_total"] == 1
    archived = tmp_path / "paychex" / first["archive_path"]
    assert archived.is_file() and first["archive_path"].endswith(
        "/mainfest-20261021.csv"
    )
    assert "/".join(str(first["processing_date"]).split("-")) in first["archive_path"]
    row = shipment_rows(env)[0]
    assert row["shipment_number"] == "000NUMBER" and row["shipper_ref"] == "00001"
    assert row["account_id"] == "0007" and row["route"] is None
    assert (
        row["notes"] == "Leave under mat|||" and row["service_type"] == "Test service"
    )
    assert str(row["order_date"]) == "2026-10-22"
    assert row["due_time"].hour == 17 and row["due_time"] > first["received_at"]
    with env.engine.connect() as connection:
        created = connection.execute(sa.select(shipment_events)).mappings().one()
        assert created["event_time"] == row["created_at"] == first["received_at"]
        assert connection.execute(sa.select(customers.c.zip)).scalar_one() == "00123"
    upload(tmp_path, "paychex", "renamed.csv", manifest_row())
    worker.tick(force=True)
    assert records(env)[1]["state"] == "skipped"
    assert len(shipment_rows(env)) == 1
    assert shipment_rows(env)[0]["updated_at"] == row["updated_at"]


def test_partial_file_keeps_valid_rows_diagnostics_and_duplicate_partial_skip(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    content = [
        manifest_row(),
        manifest_row(**{"Package ID": "bad", "Due Date/Time": "invalid"}),
        manifest_row(**{"Package ID": "00002", "Order Number": "000NUMBER"}),
    ]
    upload(tmp_path, "paychex", "mixed.csv", *content)
    worker = IntakeWorker(env.engine, tmp_path)
    worker.tick(force=True)
    run = records(env)[0]
    assert (run["state"], run["rows_completed"], run["rows_rejected"]) == (
        "completed_with_errors",
        2,
        1,
    )
    assert (
        run["archive_path"].startswith("failed/")
        and run["archive_state"] == "completed"
    )
    assert len(shipment_rows(env)) == 2
    with env.engine.connect() as connection:
        error = connection.execute(sa.select(ingestion_errors)).mappings().one()
        assert (
            error["import_id"] == run["id"] and error["source_id"] == run["source_id"]
        )
        assert error["row_number"] == 3 and error["shipper_company_id"] == int(
            env.admin.company.id
        )
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(shipment_events)
            ).scalar_one()
            == 2
        )
    upload(tmp_path, "paychex", "renamed-mixed.csv", *content)
    worker.tick(force=True)
    assert records(env)[1]["state"] == "skipped"
    assert records(env)[1]["archive_path"].startswith("failed/")


def test_manifest_updates_preserve_addresses_and_assignment(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    upload(tmp_path, "paychex", "same.csv", manifest_row())
    worker = IntakeWorker(env.engine, tmp_path)
    worker.tick(force=True)
    original = shipment_rows(env)[0]
    AccountMappingService(env.engine).configure(
        int(env.admin.company.id), env.carrier_id, "TEST.SERVICE", "0099"
    )
    upload(
        tmp_path,
        "paychex",
        "same.csv",
        manifest_row(
            **{
                "Order Number": "000CHANGED",
                "Destination Notes": "new|||",
                "Due Date/Time": "10/27/2026 5:30:00 PM",
                "Service Type/Name": "changed",
                "Order Date/Time": "10/28/2026 1:00:00 PM",
                "Destination Name": "Other address",
                "Destination City": "Other city",
            }
        ),
    )
    worker.tick(force=True)
    updated = shipment_rows(env)[0]
    assert (
        updated["account_id"] == "0007"
        and updated["recipient_id"] == original["recipient_id"]
    )
    assert (
        updated["service_type"] == original["service_type"]
        and updated["order_date"] == original["order_date"]
    )
    assert updated["shipment_number"] == "000CHANGED" and updated["notes"] == "new|||"
    assert updated["due_time"] == datetime(2026, 10, 27, 17, 30, tzinfo=UTC)
    upload(
        tmp_path,
        "paychex",
        "same.csv",
        manifest_row(
            **{
                "Order Number": "",
                "Destination Notes": "",
                "Service Type/Name": "",
                "Order Date/Time": "",
            }
        ),
    )
    worker.tick(force=True)
    preserved = shipment_rows(env)[0]
    for field in ("shipment_number", "notes", "due_time", "order_date", "service_type"):
        assert preserved[field] == updated[field]
    with env.engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(shipment_events)
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(customers)
            ).scalar_one()
            == 1
        )
    archives = list((tmp_path / "paychex" / "done").rglob("*.csv"))
    assert len(archives) == 3 and any(
        str(run["id"]) in run["archive_path"] for run in records(env)[1:]
    )


@pytest.mark.parametrize(
    "bad", [b"wrong,headers\na,b\n", b"\xff", b'Carrier ID,Package ID\n"unterminated']
)
def test_structural_failure_is_durable_and_not_retried(
    creation_env: CreationEnvironment, tmp_path: Path, bad: bytes
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    path = upload(tmp_path, "paychex", "invalid.csv", manifest_row())
    path.write_bytes(bad)
    worker = IntakeWorker(env.engine, tmp_path)
    worker.tick(force=True)
    run = records(env)[0]
    assert run["state"] == "failed" and run["archive_state"] == "completed"
    assert run["archive_path"].startswith("failed/") and run["rows_total"] == 0
    worker.tick(force=True)
    assert records(env)[0]["attempts"] == 1 and shipment_rows(env) == []


def test_trusted_source_isolation_polling_and_concurrent_claims(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    first = configure(env.engine, "paychex", 60)
    second = configure(env.engine, "test-shipper", 120)
    assert configure(env.engine, "paychex", 60) == first
    upload(tmp_path, "paychex", "one.csv", manifest_row())
    upload(tmp_path, "test-shipper", "one.csv", manifest_row())

    def tick(_: int) -> None:
        IntakeWorker(env.engine, tmp_path).tick(force=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(tick, range(2)))
    assert len(shipment_rows(env)) == 2 and len(records(env)) == 2
    assert {row["account_id"] for row in shipment_rows(env)} == {"0007", "0008"}
    with env.engine.begin() as connection:
        connection.execute(
            sources.update()
            .where(sources.c.id == first)
            .values(next_poll_at=datetime.now(UTC) + timedelta(hours=1))
        )
        connection.execute(
            sources.update()
            .where(sources.c.id == second)
            .values(next_poll_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
    upload(tmp_path, "paychex", "two.csv", manifest_row(**{"Package ID": "new"}))
    upload(tmp_path, "test-shipper", "two.csv", manifest_row(**{"Package ID": "new"}))
    IntakeWorker(env.engine, tmp_path).tick()
    assert (
        len(records(env)) == 3
        and (tmp_path / "paychex" / "upload" / "two.csv").exists()
    )
    for slug in ("ontrac", "../outside", "unknown"):
        with pytest.raises(DomainError):
            configure(env.engine, slug)


class Crash(BaseException):
    pass


def test_row_crash_recovery_does_not_replay_committed_rows(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    from app.integrations.shippers.paychex.loader import load as actual_load

    env = creation_env
    configure(env.engine, "paychex")
    upload(
        tmp_path,
        "paychex",
        "recover.csv",
        manifest_row(),
        manifest_row(**{"Package ID": "00002"}),
    )
    worker = IntakeWorker(env.engine, tmp_path)

    def crashing(*args: Any, **kwargs: Any) -> int:
        if args[2]["Package ID"] == "00002":
            raise Crash()
        return actual_load(*args, **kwargs)

    with patch("app.ingestion.worker.load", side_effect=crashing), pytest.raises(Crash):
        worker.tick(force=True)
    assert len(shipment_rows(env)) == 1
    with env.engine.begin() as connection:
        receipts = list(
            connection.execute(
                sa.select(rows.c.receipt_order).order_by(rows.c.row_number)
            ).scalars()
        )
        connection.execute(shipments.update().values(notes="do not replay"))
    worker.tick(force=True)
    assert records(env)[0]["state"] == "completed" and len(shipment_rows(env)) == 2
    assert shipment_rows(env)[0]["notes"] == "do not replay"
    with env.engine.connect() as connection:
        assert (
            list(
                connection.execute(
                    sa.select(rows.c.receipt_order).order_by(rows.c.row_number)
                ).scalars()
            )
            == receipts
        )
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(shipment_events)
            ).scalar_one()
            == 2
        )


def test_late_retry_cannot_replace_newer_field_receipts(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    upload(
        tmp_path,
        "paychex",
        "older.csv",
        manifest_row(**{"Destination Notes": "old", "Due Date/Time": "10/26/2026"}),
    )
    with patch(
        "app.ingestion.worker.load", side_effect=SQLAlchemyError("private detail")
    ):
        worker.tick(force=True)
    assert records(env)[0]["state"] == "retry_wait"
    upload(
        tmp_path,
        "paychex",
        "newer.csv",
        manifest_row(
            **{
                "Destination Notes": "new",
                "Due Date/Time": "10/29/2026",
                "Order Number": "NEW",
            }
        ),
    )
    worker.tick(force=True)
    assert shipment_rows(env)[0]["notes"] == "new"
    make_due(env)
    worker.tick(force=True)
    row = shipment_rows(env)[0]
    assert (
        row["notes"] == "new"
        and row["shipment_number"] == "NEW"
        and str(row["due_date"]) == "2026-10-29"
    )
    assert all(run["state"] == "completed" for run in records(env))


def test_archive_failure_retry_and_post_unlink_crash(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    upload(tmp_path, "paychex", "archive.csv", manifest_row())
    with patch(
        "app.ingestion.worker.files.archive_move", side_effect=OSError("storage down")
    ):
        worker.tick(force=True)
    run = records(env)[0]
    assert run["state"] == "completed" and run["archive_state"] == "retry_wait"
    with env.engine.begin() as connection:
        connection.execute(shipments.update().values(notes="retained"))
    make_due(env)
    actual_move = files.archive_move

    def crashing(*args: Any) -> None:
        actual_move(*args)
        raise Crash()

    with (
        patch("app.ingestion.worker.files.archive_move", side_effect=crashing),
        pytest.raises(Crash),
    ):
        worker.tick(force=True)
    assert not (tmp_path / "paychex" / "processing" / f"{run['id']}.csv").exists()
    make_due(env)
    worker.tick(force=True)
    assert records(env)[0]["archive_state"] == "completed"
    assert shipment_rows(env)[0]["notes"] == "retained"
    assert len(list((tmp_path / "paychex" / "done").rglob("*.csv"))) == 1


def test_bounded_processing_and_archive_retries(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    upload(tmp_path, "paychex", "database.csv", manifest_row())
    with patch("app.ingestion.worker.load", side_effect=SQLAlchemyError("private")):
        for _ in range(8):
            make_due(env)
            worker.tick(force=True)
    run = records(env)[0]
    assert (
        run["state"] == "failed" and run["attempts"] == 5 and shipment_rows(env) == []
    )
    assert run["reason_code"] == "infrastructure_exhausted"
    upload(tmp_path, "paychex", "archive.csv", manifest_row(**{"Package ID": "other"}))
    with patch(
        "app.ingestion.worker.files.archive_move", side_effect=OSError("private")
    ):
        for _ in range(8):
            make_due(env)
            worker.tick(force=True)
    run = records(env)[1]
    assert (
        run["state"] == "completed"
        and run["archive_state"] == "exhausted"
        and run["archive_attempts"] == 5
    )
    assert (tmp_path / "paychex" / "processing" / f"{run['id']}.csv").exists()


def test_archive_collision_never_overwrites_and_paths_do_not_follow_symlinks(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"untouched")
    folder = tmp_path / "paychex" / "upload"
    folder.mkdir(parents=True)
    (folder / "symlink.csv").symlink_to(outside)
    worker.tick(force=True)
    assert records(env) == [] and outside.read_bytes() == b"untouched"
    assert (folder / "symlink.csv").is_symlink()
    upload(tmp_path, "paychex", "collision.csv", manifest_row())
    with patch("app.ingestion.worker.files.archive_move", side_effect=OSError()):
        worker.tick(force=True)
    run = records(env)[0]
    target = tmp_path / "paychex" / run["archive_path"]
    target.write_bytes(b"other archive")
    make_due(env)
    worker.tick(force=True)  # detects collision and replans, never overwrites
    make_due(env)
    worker.tick(force=True)
    assert target.read_bytes() == b"other archive"
    assert records(env)[0]["archive_state"] == "completed"


def test_claim_crash_after_commit_resumes_same_arrival(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    path = upload(tmp_path, "paychex", "claim.csv", manifest_row())
    actual_unlink = Path.unlink

    def crash_on_original(target: Path, *args: Any, **kwargs: Any) -> None:
        if target == path:
            raise Crash()
        actual_unlink(target, *args, **kwargs)

    worker = IntakeWorker(env.engine, tmp_path)
    with patch.object(Path, "unlink", crash_on_original), pytest.raises(Crash):
        worker.tick(force=True)
    assert records(env)[0]["state"] == "processing" and path.exists()
    import_id = records(env)[0]["id"]
    worker.tick(force=True)
    assert len(records(env)) == 1 and records(env)[0]["id"] == import_id
    assert records(env)[0]["state"] == "completed" and not path.exists()
    assert len(shipment_rows(env)) == 1


def test_missing_order_date_generated_number_and_invalid_existing_atomicity(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    upload(
        tmp_path,
        "paychex",
        "initial.csv",
        manifest_row(**{"Order Number": "", "Order Date/Time": ""}),
    )
    worker.tick(force=True)
    original = shipment_rows(env)[0]
    assert (
        len(original["shipment_number"]) == 15 and original["shipment_number"].isalnum()
    )
    assert original["order_date"] is None
    upload(
        tmp_path,
        "paychex",
        "bad.csv",
        manifest_row(
            **{
                "Order Number": "CHANGED",
                "Destination Notes": "bad change",
                "Due Date/Time": "2026-13-01",
            }
        ),
    )
    worker.tick(force=True)
    rejected = records(env)[1]
    assert (
        rejected["state"] == "completed_with_errors" and rejected["rows_rejected"] == 1
    )
    unchanged = shipment_rows(env)[0]
    assert (
        unchanged["shipment_number"] == original["shipment_number"]
        and unchanged["notes"] == original["notes"]
        and unchanged["due_time"] == original["due_time"]
    )
    upload(
        tmp_path,
        "paychex",
        "preserve.csv",
        manifest_row(
            **{"Order Number": "", "Order Date/Time": "", "Destination Notes": "new"}
        ),
    )
    worker.tick(force=True)
    assert shipment_rows(env)[0]["shipment_number"] == original["shipment_number"]
    assert shipment_rows(env)[0]["due_time"] == original["due_time"]


def test_each_ordinary_field_has_independent_receipt_order(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    ShipmentService(env.engine).create(env.admin, shipment_input())
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    upload(
        tmp_path,
        "paychex",
        "older.csv",
        manifest_row(
            **{"Order Number": "OLDER-NUMBER", "Destination Notes": "older notes"}
        ),
    )
    with patch("app.ingestion.worker.load", side_effect=SQLAlchemyError()):
        worker.tick(force=True)
    upload(
        tmp_path,
        "paychex",
        "newer.csv",
        manifest_row(**{"Order Number": "", "Destination Notes": "newer notes"}),
    )
    worker.tick(force=True)
    make_due(env)
    worker.tick(force=True)
    row = shipment_rows(env)[0]
    assert row["notes"] == "newer notes" and row["shipment_number"] == "OLDER-NUMBER"


def test_archive_link_crash_recovers_without_collision_suffix(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    upload(tmp_path, "paychex", "linked.csv", manifest_row())
    with patch("app.ingestion.worker.files.archive_move", side_effect=OSError()):
        worker.tick(force=True)
    run = records(env)[0]
    make_due(env)
    actual_sync = files.sync

    def crashing_sync(path: Path) -> None:
        if "done" in path.parts:
            raise Crash()
        actual_sync(path)

    with (
        patch("app.ingestion.worker.files.sync", side_effect=crashing_sync),
        pytest.raises(Crash),
    ):
        worker.tick(force=True)
    spool = tmp_path / "paychex" / "processing" / f"{run['id']}.csv"
    archive = tmp_path / "paychex" / run["archive_path"]
    assert spool.exists() and archive.exists() and os.path.samefile(spool, archive)
    make_due(env)
    worker.tick(force=True)
    assert records(env)[0]["archive_state"] == "completed"
    assert len(list((tmp_path / "paychex" / "done").rglob("*.csv"))) == 1


def test_oversized_files_archive_all_original_bytes(
    creation_env: CreationEnvironment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    path = upload(tmp_path, "paychex", "large.csv", manifest_row())
    original = path.read_bytes()
    monkeypatch.setattr(files, "MAX_BYTES", 10)
    IntakeWorker(env.engine, tmp_path).tick(force=True)
    run = records(env)[0]
    assert run["state"] == "failed" and run["reason_code"] == "file_limit"
    assert (tmp_path / "paychex" / run["archive_path"]).read_bytes() == original
    assert shipment_rows(env) == []


def test_recipient_timezone_source_dates_and_validation_rollback(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    from app.shipments.schema import customers_validated

    env = creation_env
    ShipmentService(env.engine).create(env.admin, shipment_input())
    with env.engine.begin() as connection:
        validation = connection.execute(
            customers_validated.insert()
            .values(
                company_id=int(env.admin.company.id), timezone="America/Los_Angeles"
            )
            .returning(customers_validated.c.id)
        ).scalar_one()
        connection.execute(customers.update().values(validated_id=validation))
    configure(env.engine, "paychex")
    upload(
        tmp_path,
        "paychex",
        "timezone.csv",
        manifest_row(
            **{
                "Due Date/Time": "10/25/2026 5:00:00 PM",
                "Order Date/Time": "10/22/2026 11:27:00 PM",
            }
        ),
        manifest_row(
            **{"Package ID": "00002", "Due Date/Time": "11/01/2026 1:30:00 AM"}
        ),
    )
    IntakeWorker(env.engine, tmp_path).tick(force=True)
    run = records(env)[0]
    assert run["state"] == "completed_with_errors" and run["rows_rejected"] == 1
    assert shipment_rows(env)[0]["due_time"] == datetime(2026, 10, 26, 0, tzinfo=UTC)
    assert len(shipment_rows(env)) == 1


def test_source_disable_unregistered_folder_and_cli_status(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    import json
    import subprocess
    import sys

    env = creation_env
    configure(env.engine, "paychex", enabled=False)
    path = upload(tmp_path, "paychex", "private-name.csv", manifest_row())
    unrelated = upload(tmp_path, "unregistered", "unknown.csv", manifest_row())
    worker = IntakeWorker(env.engine, tmp_path)
    worker.tick(force=True)
    assert records(env) == [] and path.exists() and unrelated.exists()
    configure(env.engine, "paychex")
    worker.tick(force=True)
    result = subprocess.run(
        [sys.executable, "-m", "app.ingestion.cli", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    status = json.loads(result.stdout)
    assert status[0]["rows_completed"] == 1 and "private-name" not in result.stdout
    assert "Leave under mat" not in result.stdout
    assert unrelated.exists()


def test_unreadable_capture_has_bounded_retries_and_preserves_raw_archive(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    path = upload(tmp_path, "paychex", "unreadable.csv", manifest_row())
    original = path.read_bytes()
    with patch("app.ingestion.worker.files.capture", side_effect=PermissionError()):
        for _ in range(8):
            make_due(env)
            worker.tick(force=True)
    run = records(env)[0]
    assert len(records(env)) == 1 and run["state"] == "failed" and run["attempts"] == 5
    assert run["archive_state"] == "completed" and run["checksum"] is None
    assert (tmp_path / "paychex" / run["archive_path"]).read_bytes() == original
    assert not path.exists() and shipment_rows(env) == []


def test_exhausted_partial_capture_archives_complete_original(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    worker = IntakeWorker(env.engine, tmp_path)
    path = upload(tmp_path, "paychex", "partial-capture.csv", manifest_row())
    original = path.read_bytes()

    def partial_capture(path: Path, processing: Path, import_id: str) -> None:
        (processing / f"{import_id}.csv").write_bytes(path.read_bytes()[:10])
        raise OSError("Synthetic disk failure")

    with patch("app.ingestion.worker.files.capture", side_effect=partial_capture):
        for _ in range(6):
            make_due(env)
            worker.tick(force=True)
    run = records(env)[0]
    assert run["state"] == "failed" and run["attempts"] == 5
    assert run["archive_state"] == "completed"
    assert (tmp_path / "paychex" / run["archive_path"]).read_bytes() == original
    assert not path.exists() and shipment_rows(env) == []


def test_broken_source_does_not_starve_another_source(
    creation_env: CreationEnvironment, tmp_path: Path
) -> None:
    env = creation_env
    configure(env.engine, "paychex")
    configure(env.engine, "test-shipper")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "paychex").symlink_to(outside, target_is_directory=True)
    upload(tmp_path, "test-shipper", "good.csv", manifest_row())
    with pytest.raises(OSError):
        IntakeWorker(env.engine, tmp_path).tick(force=True)
    assert len(records(env)) == 1 and records(env)[0]["state"] == "completed"
    assert shipment_rows(env)[0]["shipper_company_id"] == int(env.other.company.id)
    assert list(outside.iterdir()) == []
