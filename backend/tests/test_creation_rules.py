from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.shipments.common import DomainError
from app.shipments.dto import AreaInput, PackageInput
from app.shipments.time_rules import default_deadline, normalize_instant


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("0", Decimal("0.00")),
        ("56.789", Decimal("56.79")),
        ("1.005", Decimal("1.01")),
        ("999.994", Decimal("999.99")),
    ],
)
def test_weight_decimal_boundaries(value: object, expected: Decimal | None) -> None:
    assert PackageInput.model_validate({"weight": value}).weight == expected


@pytest.mark.parametrize(
    "value", ["-0.001", "999.995", "1000", "NaN", "Infinity", "1e1000", True]
)
def test_invalid_weight(value: object) -> None:
    with pytest.raises(ValidationError):
        PackageInput.model_validate({"weight": value})


@pytest.mark.parametrize(
    ("processed", "expected"),
    [
        ("2026-10-21T23:59:59+00:00", "2026-10-22T17:00:00+00:00"),
        ("2026-10-22T12:00:00+00:00", "2026-10-23T17:00:00+00:00"),
        ("2026-10-23T12:00:00+00:00", "2026-10-26T17:00:00+00:00"),
        ("2026-10-24T12:00:00+00:00", "2026-10-26T17:00:00+00:00"),
        ("2026-10-25T12:00:00+00:00", "2026-10-26T17:00:00+00:00"),
        ("2026-12-31T23:59:59+00:00", "2027-01-01T17:00:00+00:00"),
    ],
)
def test_default_deadline_utc_calendar(processed: str, expected: str) -> None:
    assert default_deadline(datetime.fromisoformat(processed)).isoformat() == expected


@pytest.mark.parametrize(
    ("value", "zone", "expected"),
    [
        ("2026-10-24", None, "2026-10-24T17:00:00+00:00"),
        ("2026-10-20T17:05:10", None, "2026-10-20T17:05:10+00:00"),
        ("2026-10-20T17:05:10", "America/Los_Angeles", "2026-10-21T00:05:10+00:00"),
        ("2026-12-20T17:05:10", "America/Los_Angeles", "2026-12-21T01:05:10+00:00"),
        (
            "2026-10-20T17:05:10+02:00",
            "America/Los_Angeles",
            "2026-10-20T15:05:10+00:00",
        ),
    ],
)
def test_normalized_deadline(value: str, zone: str | None, expected: str) -> None:
    assert normalize_instant(value, zone).isoformat() == expected
    assert normalize_instant(value, zone).tzinfo == UTC


@pytest.mark.parametrize(
    ("value", "zone"),
    [
        ("2026-11-01T01:30:00", "America/Los_Angeles"),
        ("2026-03-08T02:30:00", "America/Los_Angeles"),
        ("2026-10-20T17:00:00", "Invalid/Zone"),
        ("not-a-date", None),
        ("2026-02-30", None),
        ("17:00", None),
        ("1760000000", None),
    ],
)
def test_invalid_deadline(value: str, zone: str | None) -> None:
    with pytest.raises(DomainError):
        normalize_instant(value, zone)


@pytest.mark.parametrize("value", ["", "   ", "a/b", "a.b", "x" * 65])
def test_invalid_area_name(value: str) -> None:
    with pytest.raises(ValidationError):
        AreaInput(name=value)


def test_area_names_normalize() -> None:
    assert AreaInput(name="  SFO-North_154  ").name == "sfo-north_154"
    assert AreaInput(name=" Étage 1 ").name == "étage 1"
