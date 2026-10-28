from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_serializer,
    field_validator,
)

from app.shipments.common import DomainError


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def trim(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value


class AddressInput(InputModel):
    name: Annotated[StrictStr, Field(min_length=1, max_length=255)]
    address_one: Annotated[StrictStr, Field(min_length=1, max_length=255)]
    address_two: Annotated[StrictStr, Field(max_length=255)] | None = None
    city: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    state: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    zip: Annotated[StrictStr, Field(min_length=1, max_length=32)]
    note: Annotated[StrictStr, Field(max_length=4000)] | None = None
    phone: Annotated[StrictStr, Field(max_length=64)] | None = None
    email: Annotated[StrictStr, Field(max_length=320)] | None = None


class PackageInput(InputModel):
    weight: Decimal | None = None

    @field_validator("weight")
    @classmethod
    def weight_range(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        try:
            if not value.is_finite() or value < 0 or value > 1000:
                raise ValueError("Weight must be finite and nonnegative")
            rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if rounded > Decimal("999.99"):
                raise ValueError("Weight exceeds 999.99")
            return rounded
        except InvalidOperation:
            raise ValueError("Invalid weight") from None


class ShipmentInput(InputModel):
    reference: Annotated[StrictStr, Field(min_length=1, max_length=255)]
    account_number: Annotated[StrictStr, Field(max_length=255)] | None = None
    carrier_id: Annotated[StrictStr, Field(max_length=64)] | None = None
    shipment_number: Annotated[StrictStr, Field(max_length=255)] | None = None
    reference_two: Annotated[StrictStr, Field(max_length=255)] | None = None
    service_name: Annotated[StrictStr, Field(max_length=255)] | None = None
    due_time: Annotated[StrictStr, Field(max_length=128)] | None = None
    package: PackageInput | None = None
    from_address: AddressInput
    to_address: AddressInput
    # Accepted compatibility flags have no MVP behavior or persistence.
    signature_required: bool | None = None
    sort_code: StrictStr | None = None

    def required_assignment(self) -> tuple[str, str]:
        if not self.account_number:
            raise DomainError(400, "account is required", "missing_account")
        if not self.carrier_id:
            raise DomainError(400, "carrier_id is required", "missing_service")
        return self.carrier_id, self.account_number


class ShipmentCreated(BaseModel):
    id: str
    reference: str
    shipment_number: str
    carrier_company_id: str
    account_number: str
    reference_two: str | None
    service_name: str | None
    sender_id: str
    recipient_id: str
    weight: Decimal | None
    due_time: datetime
    due_date: date
    route: int | None

    @field_serializer("due_time", when_used="json")
    def serialize_deadline(self, value: datetime) -> str:
        return value.isoformat()


class AreaInput(InputModel):
    name: Annotated[StrictStr, Field(min_length=1, max_length=64)]

    @field_validator("name")
    @classmethod
    def normalized(cls, value: str) -> str:
        value = value.lower()
        if len(value) > 64 or not all(
            character.isalnum() or character in " _-" for character in value
        ):
            raise ValueError("Invalid area name")
        return value


class AreaOutput(BaseModel):
    id: int
    name: str
