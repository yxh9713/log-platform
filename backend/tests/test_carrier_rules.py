from typing import Any

import pytest

from app.integrations.carriers.ontrac.transformer import (
    EVENTS,
    WEBHOOK_EVENTS,
    transform,
)
from app.shipments.common import DomainError


@pytest.mark.parametrize("code", list(EVENTS))
def test_exact_csv_event_mapping(code: str) -> None:
    payload = transform(
        {
            "event": code,
            "account": " 0007 ",
            "reference": "00001",
            "timestamp": "10/27/2026 5:00:00 PM",
            "status": "ignored",
            "zone": "154",
            "address_one": "ignored",
        },
        csv=True,
    )
    assert payload and payload.account == "0007" and payload.reference == "00001"
    assert payload.route == "154" and payload.time == "2026-10-27T17:00:00"
    assert payload.due_time is None


@pytest.mark.parametrize("code", list(WEBHOOK_EVENTS))
def test_webhook_event_mapping(code: str) -> None:
    assert (
        transform(
            {
                "event": code,
                "account": "0007",
                "reference": "00001",
                "time": "2026-10-27T17:00:00Z",
            }
        )
        is not None
    )


@pytest.mark.parametrize("code", ["delivered", "delivery", "Created", "UNKNOWN"])
def test_unknown_codes_ignore_optional_input(code: str) -> None:
    # Surrounding whitespace is normal input trimming, not case folding.
    result = transform(
        {"event": code, "pod": "not an image", "due_time": "nonsense"}, csv=True
    )
    assert result is None


@pytest.mark.parametrize(
    "changes",
    [
        {"reference": 123},
        {"account": ""},
        {"time": "2026-10-27"},
        {"time": "1793000000"},
        {"time": "garbage"},
        {"company_id": 2},
    ],
)
def test_known_event_required_values_and_spoofed_fields(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(DomainError):
        transform(
            {
                "event": "Delivered",
                "account": "0007",
                "reference": "00001",
                "time": "2026-10-27T17:00:00Z",
                **changes,
            }
        )


def test_csv_adapter_field_limits_do_not_change_each_other() -> None:
    from app.ingestion.files import parse
    from app.integrations.carriers.ontrac.transformer import REQUIRED_HEADERS
    from tests.test_manifest_rules import csv_bytes

    content = csv_bytes(
        {
            "account": "0007",
            "reference": "00001",
            "event": "unknown",
            "timestamp": "unused",
            "pod_image": "a" * 70_000,
        }
    )
    assert (
        len(parse(content, REQUIRED_HEADERS, field_limit=6_666_668)[0]["pod_image"])
        == 70_000
    )
    with pytest.raises(DomainError):
        parse(content, REQUIRED_HEADERS)
    assert parse(content, REQUIRED_HEADERS, field_limit=6_666_668)
