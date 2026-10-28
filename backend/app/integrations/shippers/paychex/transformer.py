"""Exact Paychex column mapping; no tenant/account inference from CSV values."""

import re
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError

from app.shipments.common import DomainError
from app.shipments.dto import ShipmentInput

REQUIRED_HEADERS = {
    "Carrier ID",
    "Package ID",
    *{
        f"{prefix} {field}"
        for prefix in ("Pickup", "Destination")
        for field in ("Name", "Address 1", "City", "State", "Zip")
    },
}


def source_time(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        for pattern, fmt in (
            (r"\d{2}/\d{2}/\d{4} \d{1,2}:\d{2}:\d{2} (AM|PM)", "%m/%d/%Y %I:%M:%S %p"),
            (r"\d{2}/\d{2}/\d{4}", "%m/%d/%Y"),
        ):
            if re.fullmatch(pattern, value):
                parsed = datetime.strptime(value, fmt)
                return parsed.isoformat() if " " in value else parsed.date().isoformat()
        if re.match(r"^\d{4}-\d{2}-\d{2}($|[T ])", value):
            return value
    except ValueError:
        pass
    raise DomainError(400, "Invalid manifest date", "invalid_source_time")


@dataclass(frozen=True)
class ManifestRecord:
    payload: ShipmentInput
    notes: str | None
    order_time: str | None


def transform(row: dict[str, str]) -> ManifestRecord:
    def optional(name: str) -> str | None:
        return row.get(name, "").strip() or None

    def address(prefix: str) -> dict[str, str | None]:
        return {
            "name": optional(f"{prefix} Name"),
            "address_one": optional(f"{prefix} Address 1"),
            "address_two": optional(f"{prefix} Address 2"),
            "city": optional(f"{prefix} City"),
            "state": optional(f"{prefix} State"),
            "zip": optional(f"{prefix} Zip"),
            **(
                {
                    "phone": optional("Destination Phone"),
                    "email": optional("Contact Email"),
                }
                if prefix == "Destination"
                else {}
            ),
        }

    notes = optional("Destination Notes")
    if notes is not None and len(notes) > 4000:
        raise DomainError(400, "Invalid manifest notes", "invalid_manifest_row")
    try:
        payload = ShipmentInput.model_validate(
            {
                "reference": optional("Package ID"),
                "carrier_id": optional("Carrier ID"),
                "shipment_number": optional("Order Number"),
                "service_name": optional("Service Type/Name"),
                "due_time": source_time(optional("Due Date/Time")),
                "from_address": address("Pickup"),
                "to_address": address("Destination"),
            }
        )
        if not payload.carrier_id:
            raise DomainError(400, "Missing manifest service", "invalid_assignment")
        return ManifestRecord(payload, notes, source_time(optional("Order Date/Time")))
    except ValidationError:
        raise DomainError(400, "Invalid manifest row", "invalid_manifest_row") from None
