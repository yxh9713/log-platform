"""Bounded, crash-recoverable storage retries, independent of carrier events."""

import hashlib
from collections.abc import Callable
from datetime import timedelta
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.ingestion.worker import now
from app.pod.schema import shipment_images as images
from app.pod.storage import DummyPodStorage, PermanentStorageError, PodStorage
from app.shipments.schema import ingestion_errors

MAX_ATTEMPTS = 5
DELAYS = (5, 30, 120, 600, 1800)


class PodWorker:
    def __init__(
        self,
        engine: Engine,
        storage: PodStorage | None = None,
        heartbeat: Callable[[], None] = lambda: None,
    ):
        self.engine = engine
        self.storage = storage if storage is not None else DummyPodStorage()
        self.heartbeat = heartbeat

    def tick(self) -> None:
        with self.engine.connect() as connection:
            identities = list(
                connection.execute(
                    sa.select(images.c.id)
                    .where(
                        images.c.state.in_(("pending", "retry_wait")),
                        images.c.next_attempt_at <= sa.func.clock_timestamp(),
                    )
                    .order_by(images.c.next_attempt_at, images.c.id)
                    .limit(20)
                ).scalars()
            )
        for image_id in identities:
            self.run_image(str(image_id))
            self.heartbeat()
        self.heartbeat()

    def run_image(self, image_id: str) -> None:
        with self.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as lock:
            key = f"pod-image:{image_id}"
            if not lock.execute(
                sa.text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                {"key": key},
            ).scalar_one():
                return
            try:
                self._image(image_id)
            finally:
                try:
                    lock.execute(
                        sa.text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                        {"key": key},
                    )
                except SQLAlchemyError:
                    lock.invalidate()

    @staticmethod
    def _fail(connection: Connection, image: sa.RowMapping, reason: str) -> None:
        connection.execute(
            images.update()
            .where(images.c.id == image["id"])
            .values(
                state="failed",
                reason_code=reason,
                updated_at=sa.func.now(),
            )
        )
        connection.execute(
            ingestion_errors.insert().values(
                shipper_company_id=image["shipper_company_id"],
                shipment_id=image["shipment_id"],
                source_type="pod_storage",
                reason_code=reason,
                image_id=image["id"],
            )
        )

    def _image(self, image_id: str) -> None:
        with self.engine.begin() as connection:
            image = (
                connection.execute(
                    sa.select(images).where(images.c.id == image_id).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if (
                image is None
                or image["state"] in ("ready", "failed")
                or image["next_attempt_at"] > now(connection)
            ):
                return
            if image["attempts"] >= MAX_ATTEMPTS:
                self._fail(connection, image, "pod_storage_exhausted")
                return
            attempt = image["attempts"] + 1
            # Persist the attempt/backoff before I/O, so a process crash is still
            # a counted attempt. The session lock prevents overlapping uploads.
            connection.execute(
                images.update()
                .where(images.c.id == image_id)
                .values(
                    state="retry_wait",
                    attempts=attempt,
                    next_attempt_at=now(connection)
                    + timedelta(seconds=DELAYS[attempt - 1]),
                    updated_at=sa.func.now(),
                )
            )
        try:
            data = bytes(image["prepared_content"])
            if (
                hashlib.sha256(data).hexdigest() != image["content_hash"]
                or len(data) != image["size_bytes"]
            ):
                raise PermanentStorageError("Prepared content mismatch")
            url = self.storage.upload(image["object_key"], data, image["content_type"])
            parsed = urlsplit(url)
            if (
                len(url) > 2048
                or parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or any(character.isspace() for character in url)
            ):
                raise PermanentStorageError("Invalid storage URL")
        except Exception as error:
            with self.engine.begin() as connection:
                if (
                    isinstance(error, (PermanentStorageError, ValueError))
                    or attempt >= MAX_ATTEMPTS
                ):
                    self._fail(
                        connection,
                        image,
                        "pod_storage_failed"
                        if attempt < MAX_ATTEMPTS
                        else "pod_storage_exhausted",
                    )
                else:
                    connection.execute(
                        images.update()
                        .where(images.c.id == image_id)
                        .values(
                            reason_code="pod_storage_unavailable",
                            next_attempt_at=now(connection)
                            + timedelta(seconds=DELAYS[attempt - 1]),
                            updated_at=sa.func.now(),
                        )
                    )
            return
        with self.engine.begin() as connection:
            connection.execute(
                images.update()
                .where(images.c.id == image_id)
                .values(
                    state="ready",
                    url=url,
                    prepared_content=None,
                    reason_code=None,
                    updated_at=sa.func.now(),
                )
            )
