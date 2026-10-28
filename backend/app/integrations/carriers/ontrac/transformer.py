"""Exact OnTrac layouts; source tenant/address/status fields never authorize edits."""

from typing import Annotated, Any

from pydantic import Field, StrictStr, ValidationError

from app.integrations.shippers.paychex.transformer import source_time
from app.shipments.common import DomainError
from app.shipments.dto import InputModel

EVENTS = {
    "Possession": "possession",
    "OutForDelivery": "out for delivery",
    "Delivery": "delivered",
    "PickUp": "picked up",
    "Exception": "attempted",
    "Returned": "returned",
}
WEBHOOK_EVENTS = {**EVENTS, "Delivered": "delivered"}
REQUIRED_HEADERS = {"account", "reference", "event", "timestamp"}
Text = Annotated[StrictStr, Field(min_length=1, max_length=255)]


class CarrierInput(InputModel):
    account: Text
    reference: Text
    event: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    time: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    shipment_number: Text | None = None
    sign: Annotated[StrictStr, Field(max_length=255)] | None = None
    notes: Annotated[StrictStr, Field(max_length=4000)] | None = None
    route: Annotated[StrictStr, Field(max_length=64)] | None = None
    due_time: Annotated[StrictStr, Field(max_length=128)] | None = None
    pod: Annotated[StrictStr, Field(max_length=6_666_668)] | None = Field(
        default=None, repr=False
    )


def transform(values: dict[str, Any], *, csv: bool = False) -> CarrierInput | None:
    event = values.get("event")
    if not isinstance(event, str) or not event.strip() or len(event) > 64:
        raise DomainError(400, "Carrier event is required", "invalid_carrier_row")
    event = event.strip()
    if event not in (EVENTS if csv else WEBHOOK_EVENTS):
        return None
    if csv:
        values = {
            **{
                key: values.get(key)
                for key in (
                    "account",
                    "reference",
                    "shipment_number",
                    "sign",
                    "notes",
                    "due_time",
                )
            },
            "event": event,
            "time": values.get("timestamp"),
            "route": values.get("zone"),
            "pod": values.get("pod_image"),
        }
    try:
        payload = CarrierInput.model_validate(values)
        # Date-only event times are not scan timestamps. Deadlines may be dates.
        parsed = source_time(payload.time)
        if parsed is None or len(parsed) == 10:
            raise DomainError(400, "Invalid carrier timestamp", "invalid_event_time")
        return payload.model_copy(update={"time": parsed})
    except ValidationError:
        raise DomainError(
            400, "Invalid carrier update", "invalid_carrier_row"
        ) from None
