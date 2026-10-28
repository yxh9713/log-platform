"""PostgreSQL-backed intake and durable row work; no Redis-only queue state."""

import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.carriers.service import CarrierFailure
from app.ingestion import files
from app.ingestion.schema import ingestion_imports as imports
from app.ingestion.schema import ingestion_rows as rows
from app.ingestion.schema import ingestion_source as sources
from app.integrations.carriers.ontrac.loader import load as load_carrier
from app.integrations.carriers.ontrac.transformer import (
    REQUIRED_HEADERS as CARRIER_HEADERS,
)
from app.integrations.shippers.paychex.loader import load
from app.shipments.accounts import company_type
from app.shipments.common import DomainError
from app.shipments.schema import ingestion_errors

FINISHED = ("completed", "completed_with_errors", "failed", "skipped")
MAX_ATTEMPTS = 5
DELAYS = (5, 30, 120, 600, 1800)


def now(connection: Connection) -> datetime:
    return cast(
        datetime, connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    )


class IntakeWorker:
    def __init__(
        self, engine: Engine, root: Path, heartbeat: Callable[[], None] = lambda: None
    ):
        self.engine, self.root, self.heartbeat = (
            engine,
            root.resolve(strict=True),
            heartbeat,
        )

    def tick(self, *, force: bool = False) -> None:
        with self.engine.connect() as connection:
            source_ids = list(
                connection.execute(
                    sa.select(sources.c.id)
                    .where(sources.c.enabled.is_(True))
                    .order_by(sources.c.id)
                ).scalars()
            )
        source_error: OSError | DomainError | None = None
        for source_id in source_ids:
            try:
                self.run_source(int(source_id), force=force)
            except (OSError, DomainError) as error:
                # A broken folder/configuration must not starve other sources.
                # Still fail the tick so health/logs expose the problem.
                source_error = source_error or error
        if source_error is not None:
            raise source_error
        self.heartbeat()

    def run_source(self, source_id: int, *, force: bool = False) -> None:
        # Session lock is released on process/connection death. A second worker
        # cannot mutate files or run the same source concurrently.
        with self.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as lock:
            key = f"ingestion-source:{source_id}"
            acquired = lock.execute(
                sa.text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                {"key": key},
            ).scalar_one()
            if not acquired:
                return
            try:
                self._source(source_id, force)
            finally:
                try:
                    lock.execute(
                        sa.text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                        {"key": key},
                    )
                except SQLAlchemyError:
                    lock.invalidate()

    def _source(self, source_id: int, force: bool) -> None:
        with self.engine.begin() as connection:
            source = (
                connection.execute(
                    sa.select(sources).where(
                        sources.c.id == source_id, sources.c.enabled.is_(True)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if source is None:
                return
            company_type(
                connection,
                source["company_id"],
                1 if source["adapter"] == "ontrac_csv" else 2,
            )
            clock = now(connection)
            poll = force or source["next_poll_at"] <= clock
            if poll:
                connection.execute(
                    sources.update()
                    .where(sources.c.id == source_id)
                    .values(
                        next_poll_at=clock
                        + timedelta(seconds=source["poll_interval_seconds"])
                    )
                )
        source_dir = files.source_directory(self.root, source["folder"])
        upload = files.directory(source_dir / "upload")
        files.directory(source_dir / "processing")
        if poll:
            for path in sorted(upload.iterdir()):
                if not path.name.endswith(".csv"):
                    continue
                try:
                    if stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                        self._claim(source, path)
                except OSError:
                    # Never follow a symlink or leak a pathname/input in logs.
                    with self.engine.begin() as connection:
                        self._error(connection, source, None, "file_claim_unavailable")
        with self.engine.connect() as connection:
            import_ids = list(
                connection.execute(
                    sa.select(imports.c.id)
                    .where(
                        imports.c.source_id == source_id,
                        sa.or_(
                            imports.c.state.not_in(FINISHED),
                            imports.c.archive_state.in_(("pending", "retry_wait")),
                        ),
                    )
                    .order_by(imports.c.received_at, imports.c.id)
                ).scalars()
            )
        for import_id in import_ids:
            self._process(source, source_dir, str(import_id))
            self.heartbeat()

    def _claim(self, source: sa.RowMapping, path: Path) -> str:
        identity = files.fingerprint(path.stat(follow_symlinks=False))
        with self.engine.begin() as connection:
            previous = connection.execute(
                sa.select(imports.c.id).where(
                    imports.c.source_id == source["id"],
                    imports.c.original_name == path.name,
                    imports.c.file_identity == identity,
                )
            ).scalar_one_or_none()
            if previous is not None:
                return str(previous)
            import_id = str(uuid4())
            clock = now(connection)
            connection.execute(
                imports.insert().values(
                    id=import_id,
                    source_id=source["id"],
                    original_name=path.name,
                    file_identity=identity,
                    received_at=clock,
                    processing_date=clock.astimezone(UTC).date(),
                    next_attempt_at=clock,
                    archive_next_at=clock,
                    state="pending",
                )
            )
            return import_id

    @staticmethod
    def _remove_original(source_dir: Path, run: sa.RowMapping) -> None:
        original = source_dir / "upload" / run["original_name"]
        try:
            if (
                files.fingerprint(original.stat(follow_symlinks=False))
                == run["file_identity"]
            ):
                original.unlink()
                files.sync(original.parent)
        except FileNotFoundError:
            pass

    def _prepare(self, source_dir: Path, run: sa.RowMapping) -> sa.RowMapping:
        if run["checksum"] is None:
            original = source_dir / "upload" / run["original_name"]
            if (
                files.fingerprint(original.stat(follow_symlinks=False))
                != run["file_identity"]
            ):
                raise DomainError(400, "Finalized input changed", "source_changed")
            processing = source_dir / "processing"
            spool = processing / f"{run['id']}.csv"
            # No business row can have been accepted before checksum is durable.
            # Replace only this import's incomplete capture after a crash.
            if spool.exists() or spool.is_symlink():
                spool.unlink()
            _, digest, identity = files.capture(original, processing, run["id"])
            if identity != run["file_identity"]:
                raise DomainError(400, "Finalized input changed", "source_changed")
            with self.engine.begin() as connection:
                canonical = connection.execute(
                    sa.select(imports.c.id).where(
                        imports.c.source_id == run["source_id"],
                        imports.c.checksum == digest,
                        imports.c.dedupe_of_id.is_(None),
                        imports.c.id != run["id"],
                    )
                ).scalar_one_or_none()
                connection.execute(
                    imports.update()
                    .where(imports.c.id == run["id"])
                    .values(
                        checksum=digest,
                        dedupe_of_id=canonical,
                        state="duplicate_waiting" if canonical else "processing",
                    )
                )
            run = self._get(run["id"])
        self._remove_original(source_dir, run)
        return run

    def _row(
        self,
        source: sa.RowMapping,
        run: sa.RowMapping,
        row_number: int,
        values: dict[str, str],
    ) -> None:
        with self.engine.begin() as connection:
            receipt = (
                connection.execute(
                    sa.select(rows)
                    .where(
                        rows.c.import_id == run["id"], rows.c.row_number == row_number
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if receipt["state"] != "pending":
                return
            try:
                with connection.begin_nested():
                    outcome = "accepted"
                    if source["adapter"] == "ontrac_csv":
                        result = load_carrier(
                            connection,
                            source["company_id"],
                            values,
                            receipt["receipt_order"],
                        )
                        shipment_id, outcome = result.shipment_id, result.outcome
                    else:
                        shipment_id = load(
                            connection,
                            source["company_id"],
                            values,
                            run["received_at"],
                            receipt["receipt_order"],
                        )
            except DomainError as error:
                if error.status >= 500:
                    raise
                self._error(
                    connection,
                    source,
                    run["id"],
                    error.code,
                    row_number,
                    values.get("reference")
                    if source["adapter"] == "ontrac_csv"
                    else values.get("Package ID"),
                    error.tenant if isinstance(error, CarrierFailure) else None,
                    values.get("account"),
                )
                connection.execute(
                    rows.update()
                    .where(
                        rows.c.import_id == run["id"], rows.c.row_number == row_number
                    )
                    .values(state="rejected", reason_code=error.code)
                )
                counter = "rows_rejected"
            else:
                connection.execute(
                    rows.update()
                    .where(
                        rows.c.import_id == run["id"], rows.c.row_number == row_number
                    )
                    .values(state="completed", shipment_id=shipment_id, outcome=outcome)
                )
                counter = "rows_completed"
                if outcome in ("duplicate", "ignored"):
                    name = "rows_" + outcome
                    # Commit the subtype counter together with rows_completed so
                    # the database counter constraint holds at every statement.
                    connection.execute(
                        imports.update()
                        .where(imports.c.id == run["id"])
                        .values(
                            rows_completed=imports.c.rows_completed + 1,
                            **{name: imports.c[name] + 1},
                        )
                    )
                    self.heartbeat()
                    return
            connection.execute(
                imports.update()
                .where(imports.c.id == run["id"])
                .values({counter: imports.c[counter] + 1})
            )
        self.heartbeat()

    def _process(self, source: sa.RowMapping, source_dir: Path, import_id: str) -> None:
        with self.engine.begin() as connection:
            run = (
                connection.execute(sa.select(imports).where(imports.c.id == import_id))
                .mappings()
                .one()
            )
            clock = now(connection)
            if run["state"] == "duplicate_waiting":
                canonical = (
                    connection.execute(
                        sa.select(imports).where(
                            imports.c.id == run["dedupe_of_id"],
                            imports.c.source_id == source["id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                if canonical["state"] not in FINISHED:
                    return
                connection.execute(
                    imports.update()
                    .where(imports.c.id == import_id)
                    .values(
                        state="skipped",
                        reason_code="duplicate_completed"
                        if canonical["state"] == "completed"
                        else "duplicate_failed",
                    )
                )
            elif run["state"] not in FINISHED:
                if run["next_attempt_at"] > clock:
                    return
                if run["attempts"] >= MAX_ATTEMPTS:
                    self._fail(connection, source, run, "infrastructure_exhausted")
                else:
                    connection.execute(
                        imports.update()
                        .where(imports.c.id == import_id)
                        .values(state="processing", attempts=imports.c.attempts + 1)
                    )
        run = self._get(import_id)
        spool = source_dir / "processing" / f"{import_id}.csv"
        if run["state"] == "processing":
            try:
                run = self._prepare(source_dir, run)
                if run["state"] == "duplicate_waiting":
                    self._process(source, source_dir, import_id)
                    return
                data, _ = files.read_regular(spool)
                if files.checksum(data) != run["checksum"]:
                    raise DomainError(400, "Snapshot changed", "snapshot_changed")
                values = (
                    files.parse(data, CARRIER_HEADERS, field_limit=6_666_668)
                    if source["adapter"] == "ontrac_csv"
                    else files.parse(data)
                )
                with self.engine.begin() as connection:
                    if not run["materialized"]:
                        if values:
                            connection.execute(
                                rows.insert(),
                                [
                                    {"import_id": import_id, "row_number": index + 2}
                                    for index in range(len(values))
                                ],
                            )
                        connection.execute(
                            imports.update()
                            .where(imports.c.id == import_id)
                            .values(materialized=True, rows_total=len(values))
                        )
                for index, value in enumerate(values, 2):
                    self._row(source, run, index, value)
                with self.engine.begin() as connection:
                    current = connection.execute(
                        sa.select(imports.c.rows_rejected).where(
                            imports.c.id == import_id
                        )
                    ).scalar_one()
                    connection.execute(
                        imports.update()
                        .where(imports.c.id == import_id)
                        .values(
                            state="completed_with_errors" if current else "completed",
                            reason_code=None,
                        )
                    )
            except DomainError as error:
                if error.status >= 500:
                    self._retry(source, import_id)
                    return
                with self.engine.begin() as connection:
                    self._fail(connection, source, run, error.code)
            except (OSError, SQLAlchemyError):
                self._retry(source, import_id)
                return
        self._archive(source, source_dir, import_id)

    def _get(self, import_id: str) -> sa.RowMapping:
        with self.engine.connect() as connection:
            return (
                connection.execute(sa.select(imports).where(imports.c.id == import_id))
                .mappings()
                .one()
            )

    @staticmethod
    def _error(
        connection: Connection,
        source: sa.RowMapping,
        import_id: str | None,
        code: str,
        row_number: int | None = None,
        reference: str | None = None,
        tenant: int | None = None,
        account: str | None = None,
    ) -> None:
        connection.execute(
            ingestion_errors.insert().values(
                shipper_company_id=tenant
                if source["adapter"] == "ontrac_csv"
                else source["company_id"],
                carrier_company_id=source["company_id"]
                if source["adapter"] == "ontrac_csv"
                else None,
                received_account=account.strip()
                if account and len(account) <= 255
                else None,
                source_id=source["id"],
                import_id=import_id,
                row_number=row_number,
                source_type="carrier_csv"
                if source["adapter"] == "ontrac_csv"
                else "manifest",
                reason_code=code,
                received_reference=reference.strip()
                if reference and len(reference) <= 255
                else None,
            )
        )

    def _fail(
        self,
        connection: Connection,
        source: sa.RowMapping,
        run: sa.RowMapping,
        code: str,
    ) -> None:
        connection.execute(
            imports.update()
            .where(imports.c.id == run["id"])
            .values(state="failed", reason_code=code)
        )
        self._error(connection, source, run["id"], code)

    def _retry(self, source: sa.RowMapping, import_id: str) -> None:
        with self.engine.begin() as connection:
            run = (
                connection.execute(sa.select(imports).where(imports.c.id == import_id))
                .mappings()
                .one()
            )
            if run["attempts"] >= MAX_ATTEMPTS:
                self._fail(connection, source, run, "infrastructure_exhausted")
            else:
                connection.execute(
                    imports.update()
                    .where(imports.c.id == import_id)
                    .values(
                        state="retry_wait",
                        reason_code="infrastructure_unavailable",
                        next_attempt_at=now(connection)
                        + timedelta(seconds=DELAYS[run["attempts"] - 1]),
                    )
                )

    def _archive(self, source: sa.RowMapping, source_dir: Path, import_id: str) -> None:
        run = self._get(import_id)
        if run["state"] not in FINISHED or run["archive_state"] in (
            "completed",
            "exhausted",
        ):
            return
        with self.engine.begin() as connection:
            clock = now(connection)
            if run["archive_next_at"] > clock:
                return
            if run["archive_attempts"] >= MAX_ATTEMPTS:
                connection.execute(
                    imports.update()
                    .where(imports.c.id == import_id)
                    .values(archive_state="exhausted")
                )
                self._error(connection, source, import_id, "archive_exhausted")
                return
            connection.execute(
                imports.update()
                .where(imports.c.id == import_id)
                .values(archive_attempts=imports.c.archive_attempts + 1)
            )
        try:
            spool = source_dir / "processing" / f"{import_id}.csv"
            if run["checksum"] is None:
                # An unreadable regular file exhausts bounded capture retries,
                # then archives without reading or discarding any input bytes.
                archived = (
                    run["archive_path"] and (source_dir / run["archive_path"]).exists()
                )
                raw_spool = spool.exists() and (
                    files.fingerprint(spool.stat(follow_symlinks=False))
                    == run["file_identity"]
                )
                if not archived and not raw_spool:
                    original = source_dir / "upload" / run["original_name"]
                    if (
                        files.fingerprint(original.stat(follow_symlinks=False))
                        != run["file_identity"]
                    ):
                        raise OSError("Original input unavailable")
                    # Failed capture may have left a truncated private copy.
                    # Archive the original inode, never that incomplete copy.
                    if spool.exists() or spool.is_symlink():
                        spool.unlink()
                    os.link(original, spool, follow_symlinks=False)
                    files.sync(spool.parent)
                if not archived:
                    self._remove_original(source_dir, run)
            if run["archive_path"] is None:
                outcome = (
                    "done"
                    if run["state"] == "completed"
                    or run["reason_code"] == "duplicate_completed"
                    else "failed"
                )
                target = files.archive_target(
                    source_dir,
                    outcome,
                    str(run["processing_date"]),
                    run["original_name"],
                    import_id,
                )
                relative = str(target.relative_to(source_dir))
                with self.engine.begin() as connection:
                    connection.execute(
                        imports.update()
                        .where(imports.c.id == import_id)
                        .values(archive_path=relative)
                    )
            else:
                relative = run["archive_path"]
                target = source_dir / relative
                # Revalidate all bound directories during recovery as well.
                current = source_dir
                for part in Path(relative).parts[:-1]:
                    current = files.directory(current / part)
            files.archive_move(spool, target, run["checksum"], run["file_identity"])
            with self.engine.begin() as connection:
                connection.execute(
                    imports.update()
                    .where(imports.c.id == import_id)
                    .values(archive_state="completed")
                )
        except FileExistsError:
            with self.engine.begin() as connection:
                connection.execute(
                    imports.update()
                    .where(imports.c.id == import_id)
                    .values(
                        archive_path=None,
                        archive_state="retry_wait",
                        archive_next_at=now(connection) + timedelta(seconds=5),
                    )
                )
        except (OSError, SQLAlchemyError):
            with self.engine.begin() as connection:
                current_run = connection.execute(
                    sa.select(imports.c.archive_attempts).where(
                        imports.c.id == import_id
                    )
                ).scalar_one()
                exhausted = current_run >= MAX_ATTEMPTS
                connection.execute(
                    imports.update()
                    .where(imports.c.id == import_id)
                    .values(
                        archive_state="exhausted" if exhausted else "retry_wait",
                        archive_next_at=now(connection)
                        + timedelta(seconds=DELAYS[min(current_run - 1, 4)]),
                    )
                )
                if exhausted:
                    self._error(connection, source, import_id, "archive_exhausted")
