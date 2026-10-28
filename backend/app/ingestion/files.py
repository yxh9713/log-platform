"""Restricted local snapshots and non-overwriting, crash-recoverable archives."""

import csv
import hashlib
import io
import os
import stat
from pathlib import Path
from uuid import uuid4

from app.integrations.shippers.paychex.transformer import REQUIRED_HEADERS
from app.shipments.common import DomainError

MAX_BYTES = 20_000_000
MAX_ROWS = 20_000
MAX_FIELD = 65_536
# csv's parser ceiling is process-global. Keep it fixed across source threads;
# enforce each adapter's smaller field bound below instead of racing setters.
csv.field_size_limit(6_666_668)


def directory(path: Path) -> Path:
    # Check every component below the trusted root; callers pass only bound
    # folder names/UUIDs and filename.name, never CSV-supplied paths.
    if path.is_symlink():
        raise OSError("Symlink directories are not allowed")
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise OSError("Expected a directory")
    return path


def source_directory(root: Path, folder: str) -> Path:
    root = root.resolve(strict=True)
    return directory(root / folder)


def fingerprint(info: os.stat_result) -> str:
    return f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}"


def read_regular(path: Path) -> tuple[bytes, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise OSError("Expected a regular file")
        if before.st_size > MAX_BYTES:
            raise DomainError(400, "Manifest is too large", "file_limit")
        data = stream.read(MAX_BYTES + 1)
        if fingerprint(before) != fingerprint(os.fstat(stream.fileno())):
            raise OSError("Finalized file changed during read")
    return data, fingerprint(before)


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def parse(
    data: bytes,
    required_headers: set[str] = REQUIRED_HEADERS,
    *,
    field_limit: int = MAX_FIELD,
) -> list[dict[str, str]]:
    if len(data) > MAX_BYTES:
        raise DomainError(400, "Manifest is too large", "file_limit")
    try:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames
        if (
            not headers
            or len(headers) != len(set(headers))
            or not required_headers <= set(headers)
        ):
            raise DomainError(400, "Invalid manifest headers", "invalid_headers")
        if any(len(header) > field_limit for header in headers):
            raise DomainError(400, "CSV field limit exceeded", "file_limit")
        rows: list[dict[str, str]] = []
        for row in reader:
            if len(rows) >= MAX_ROWS:
                raise DomainError(400, "Manifest row limit exceeded", "file_limit")
            # Width failures are recorded as rejected logical rows, not silently
            # discarded. Malformed quoting/encoding is a structural file failure.
            if None in row or any(value is None for value in row.values()):
                rows.append({"__invalid_width__": "1"})
            else:
                if any(len(value) > field_limit for value in row.values()):
                    raise DomainError(400, "CSV field limit exceeded", "file_limit")
                rows.append(dict(row))
        return rows
    except (UnicodeError, csv.Error, ValueError):
        raise DomainError(400, "Unreadable manifest", "invalid_csv") from None


def archive_target(
    source: Path, outcome: str, day: str, filename: str, import_id: str
) -> Path:
    target_dir = source
    for part in (outcome, *day.split("-")):
        target_dir = directory(target_dir / part)
    target = target_dir / filename
    if target.exists() or target.is_symlink():
        target = target_dir / f"{Path(filename).stem[:40]}.{import_id}.csv"
    if target.exists() or target.is_symlink():
        target = (
            target_dir / f"{Path(filename).stem[:40]}.{import_id}.{uuid4().hex[:8]}.csv"
        )
    return target


def archive_move(
    source: Path, target: Path, expected: str | None, identity: str | None = None
) -> None:
    if not source.exists():
        if (
            (file_checksum(target) != expected)
            if expected is not None
            else (fingerprint(target.stat(follow_symlinks=False)) != identity)
        ):
            raise OSError("Archive content mismatch")
        return
    if target.exists() and os.path.samestat(
        os.stat(source, follow_symlinks=False), os.stat(target, follow_symlinks=False)
    ):
        source.unlink()
    else:
        os.link(source, target, follow_symlinks=False)  # atomic no-overwrite
        sync(target.parent)
        source.unlink()
    sync(source.parent)


def capture(path: Path, processing: Path, import_id: str) -> tuple[Path, str, str]:
    """Snapshot/hash even oversized input in bounded chunks, preserving all bytes."""
    target = processing / f"{import_id}.csv"
    source_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(source_fd, "rb") as incoming:
        before = os.fstat(incoming.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise OSError("Expected a regular file")
        destination_fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(destination_fd, "wb") as outgoing:
            while chunk := incoming.read(1024 * 1024):
                outgoing.write(chunk)
                digest.update(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if fingerprint(before) != fingerprint(os.fstat(incoming.fileno())):
            target.unlink()
            raise OSError("Finalized file changed during capture")
    sync(processing)
    return target, digest.hexdigest(), fingerprint(before)


def file_checksum(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("Expected a regular file")
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
