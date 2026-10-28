import csv
import io
from pathlib import Path
from uuid import uuid4

import pytest

from app.ingestion import files
from app.integrations.shippers.paychex.transformer import (
    REQUIRED_HEADERS,
    source_time,
    transform,
)
from app.shipments.common import DomainError


def manifest_row(**changes: str) -> dict[str, str]:
    row = {
        "Carrier ID": "TEST.SERVICE",
        "Order Number": "000NUMBER",
        "Package ID": "00001",
        "Service Type/Name": "Test service",
        "Order Date/Time": "10/22/2026 12:27:00 PM",
        "Due Date/Time": "",
        "Destination Notes": "Leave under mat|||",
        "Pickup Name": "Test recipient",
        "Destination Name": "Test recipient",
        "Destination Phone": "0012345678",
        "Contact Email": "test@example.test",
        "Destination Route": "154",
        "Pickup Address 3": "ignored",
        "Destination Address 3": "ignored",
    }
    for prefix in ("Pickup", "Destination"):
        row.update(
            {
                f"{prefix} Address 1": "1 Test Way",
                f"{prefix} Address 2": "",
                f"{prefix} City": "Test City",
                f"{prefix} State": "TS",
                f"{prefix} Zip": "00123",
            }
        )
    return {**row, **changes}


def csv_bytes(*values: dict[str, str]) -> bytes:
    stream = io.StringIO(newline="")
    fieldnames = list(values[0]) if values else list(REQUIRED_HEADERS)
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(values)
    return stream.getvalue().encode()


def test_exact_manifest_mapping_and_ignored_fields() -> None:
    record = transform(
        manifest_row(**{"Package ID": " 000ABC ", "Order Number": " 000123 "})
    )
    assert record.payload.reference == "000ABC"
    assert record.payload.shipment_number == "000123"
    assert record.payload.account_number is None
    assert record.payload.from_address.zip == record.payload.to_address.zip == "00123"
    assert record.payload.to_address.phone == "0012345678"
    assert record.notes == "Leave under mat|||"
    assert record.order_time == "2026-10-22T12:27:00"
    assert "route" not in record.payload.model_dump()
    assert "address_three" not in record.payload.to_address.model_dump()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("10/25/2026 1:02:03 PM", "2026-10-25T13:02:03"),
        ("10/25/2026", "2026-10-25"),
        ("2026-10-25T14:00:00-07:00", "2026-10-25T14:00:00-07:00"),
        ("", None),
    ],
)
def test_source_date_formats(value: str, expected: str | None) -> None:
    assert source_time(value) == expected


@pytest.mark.parametrize(
    "value", ["10/32/2026", "10/25/2026 25:00:00 PM", "1792970000", "12:00", "garbage"]
)
def test_invalid_source_date(value: str) -> None:
    with pytest.raises(DomainError):
        source_time(value)


@pytest.mark.parametrize(
    "content",
    [b"", b"wrong,headers\n1,2\n", b"\xff", b"a\x00b", b"Carrier ID,Carrier ID\nx,y\n"],
)
def test_invalid_structure(content: bytes) -> None:
    with pytest.raises(DomainError):
        files.parse(content)


def test_parser_bom_quoted_values_width_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = csv_bytes(manifest_row(**{"Destination Notes": "a,b\nsecond line"}))
    assert (
        files.parse(b"\xef\xbb\xbf" + content)[0]["Destination Notes"]
        == "a,b\nsecond line"
    )
    assert files.parse(content + b"a,b\n")[-1] == {"__invalid_width__": "1"}
    monkeypatch.setattr(files, "MAX_BYTES", 1)
    with pytest.raises(DomainError):
        files.parse(content)
    monkeypatch.setattr(files, "MAX_BYTES", 20_000_000)
    monkeypatch.setattr(files, "MAX_ROWS", 1)
    with pytest.raises(DomainError):
        files.parse(csv_bytes(manifest_row(), manifest_row()))


def test_capture_restricts_paths_and_preserves_oversized_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = tmp_path / "mainfest.csv"
    upload.write_bytes(b"abcdefghij")
    processing = files.directory(tmp_path / "processing")
    monkeypatch.setattr(files, "MAX_BYTES", 3)
    snapshot, digest, _ = files.capture(upload, processing, str(uuid4()))
    assert snapshot.read_bytes() == upload.read_bytes()
    assert snapshot.stat().st_mode & 0o777 == 0o600
    with pytest.raises(DomainError):
        files.read_regular(snapshot)
    target = tmp_path / "archive.csv"
    files.archive_move(snapshot, target, digest)
    assert target.read_bytes() == b"abcdefghij"
    files.archive_move(
        snapshot, target, digest
    )  # recovery after unlink/checkpoint loss
    link = tmp_path / "symlink.csv"
    link.symlink_to(target)
    with pytest.raises(OSError):
        files.capture(link, processing, str(uuid4()))
    with pytest.raises(OSError):
        files.directory(link)
