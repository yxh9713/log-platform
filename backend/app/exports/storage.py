"""Local development artifacts; no external upload or public S3 claim."""

import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from app.shipments.common import DomainError


def artifact(root: Path, identity: str, filename: str) -> Path:
    safe_id = str(UUID(identity))
    if not re.fullmatch(r"shipment-\d{4}-\d{2}-\d{2}\.csv", filename):
        raise ValueError("Invalid artifact name")
    directory = root / safe_id
    if root.is_symlink() or directory.is_symlink():
        raise ValueError("Invalid export directory")
    return directory / filename


def open_download(
    root: Path, identity: str, filename: str, expected_size: int
) -> Iterator[bytes]:
    try:
        path = artifact(root, identity, filename)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size:
            os.close(descriptor)
            raise ValueError("Artifact mismatch")
        stream = os.fdopen(descriptor, "rb")
    except (OSError, ValueError):
        raise DomainError(503, "Export file is temporarily unavailable") from None

    def chunks() -> Iterator[bytes]:
        with stream:
            while data := stream.read(65536):
                yield data

    return chunks()
