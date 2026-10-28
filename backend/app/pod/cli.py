"""Trusted operator control for POD storage only; never replays carrier events."""

import argparse
import json
import time
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.pod.schema import shipment_images as images
from app.pod.worker import PodWorker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "once", "status"):
        commands.add_parser(name)
    retry = commands.add_parser("retry")
    retry.add_argument("--image-id", type=UUID, required=True)
    args = parser.parse_args()
    engine = create_database_engine(DatabaseSettings())
    try:
        if args.command == "status":
            with engine.connect() as connection:
                rows = connection.execute(
                    sa.select(
                        images.c.id,
                        images.c.shipment_id,
                        images.c.state,
                        images.c.attempts,
                        images.c.reason_code,
                        images.c.size_bytes,
                        images.c.width,
                        images.c.height,
                    )
                    .order_by(images.c.created_at.desc())
                    .limit(100)
                ).mappings()
                print(json.dumps([dict(row) for row in rows], default=str))
        elif args.command == "retry":
            with engine.begin() as connection:
                changed = connection.execute(
                    images.update()
                    .where(
                        images.c.id == str(args.image_id),
                        images.c.state == "failed",
                        images.c.prepared_content.is_not(None),
                    )
                    .values(
                        state="pending",
                        attempts=0,
                        reason_code=None,
                        next_attempt_at=sa.func.now(),
                        updated_at=sa.func.now(),
                    )
                    .returning(images.c.id)
                ).scalar_one_or_none()
                print(json.dumps({"image_retry_scheduled": changed is not None}))
        else:
            worker = PodWorker(engine, heartbeat=Path("/tmp/pod-heartbeat").touch)
            if args.command == "once":
                worker.tick()
                print(json.dumps({"image_scan_completed": True}))
            else:
                while True:
                    try:
                        worker.tick()
                    except SQLAlchemyError:
                        print(
                            json.dumps(
                                {"worker": "pod", "outcome": "database_unavailable"}
                            ),
                            flush=True,
                        )
                    time.sleep(1)
    except (SQLAlchemyError, OSError, ValueError):
        print(json.dumps({"error": "POD storage failed; inspect image status"}))
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
