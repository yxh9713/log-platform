"""Trusted local export worker; no external credentials or services."""

import argparse
import json
import time
from pathlib import Path

from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from app.config import DatabaseSettings
from app.db.connection import create_database_engine
from app.exports.worker import ExportWorker


class ExportSettings(DatabaseSettings):
    export_root: Path = Field(default=Path("/data/exports"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "once"))
    args = parser.parse_args()
    settings = ExportSettings()
    engine = create_database_engine(settings)
    worker = ExportWorker(
        engine, settings.export_root, Path("/tmp/export-heartbeat").touch
    )
    try:
        if args.command == "once":
            worker.tick()
            print(json.dumps({"export_scan_completed": True}))
        else:
            while True:
                try:
                    worker.tick()
                except (SQLAlchemyError, OSError):
                    print(
                        json.dumps(
                            {"worker": "export", "outcome": "temporarily_unavailable"}
                        ),
                        flush=True,
                    )
                time.sleep(1)
    except (SQLAlchemyError, OSError, ValueError):
        print(json.dumps({"error": "Export scan unavailable"}))
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
