"""P5 read contracts, shared by OpenAPI and PostgreSQL query services."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

LookupField = Literal["reference", "shipment_number"]
Status = Literal["Delivered", "Undelivered", "Void"]
PositiveId = Annotated[int, Field(ge=1, le=9223372036854775807)]


class Paging(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    page: Annotated[int, Field(ge=1, le=2147483647)] = 1
    length: Annotated[int, Field(ge=1, le=100)] = 10


class TrackingQuery(Paging):
    start_date: date | None = None
    end_date: date | None = None
    date_type: Literal["due_date", "order_date", "deliver_time", "created_at"] = (
        "due_date"
    )
    account: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    status: Literal["delivered", "undelivered"] | None = None
    exception: Literal["attempted", "void", "returned"] | None = None
    area: Annotated[list[PositiveId], Field(max_length=100)] = []
    sort: Literal[
        "id",
        "shipment_number",
        "reference",
        "route",
        "company",
        "city",
        "zip",
        "pod_name",
        "deliver_time",
        "due_time",
        "status",
    ] = "due_time"
    direction: Literal["asc", "desc"] = "asc"
    export: Literal[0, 1] = 0

    @field_validator("export", mode="before")
    @classmethod
    def ordinary_read(cls, value: object) -> object:
        return int(value) if isinstance(value, str) and value in ("0", "1") else value

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def calendar_date(cls, value: object) -> object:
        if value is not None and not isinstance(value, date):
            if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", value
            ):
                raise ValueError("Expected YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def date_range(self) -> "TrackingQuery":
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Both date bounds are required")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Date range is reversed")
        return self


class SearchQuery(Paging):
    identifier: Annotated[str, Field(min_length=1, max_length=255)]
    field: LookupField = "reference"

    @field_validator("identifier", mode="before")
    @classmethod
    def trim_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class LocalTimes(BaseModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_value(self, value: object) -> object:
        return value.isoformat() if isinstance(value, datetime) else value


class SearchRow(BaseModel):
    id: str
    shipment_number: str
    reference: str
    route: str | None
    address_one: str
    city: str
    state: str
    zip: str


class SearchResult(BaseModel):
    identifier: str
    field: LookupField
    items: list[SearchRow]
    total: int
    page: int
    length: int
    pages: int


class TrackingRow(LocalTimes):
    id: str
    shipment_number: str
    reference: str
    reference_two: str | None
    account: str
    carrier: str
    service_name: str | None
    route_id: int | None
    route: str | None
    company: str
    address_one: str
    address_two: str | None
    city: str
    state: str
    zip: str
    status: Status
    pod_name: str | None
    deliver_time: datetime | None
    due_time: datetime
    due_date: date
    weight: Decimal | None


class Metrics(BaseModel):
    total: int
    delivered: int
    undelivered: int
    void: int
    otp: float


class TrackingResult(BaseModel):
    items: list[TrackingRow]
    total: int
    page: int
    length: int
    pages: int
    start_date: date
    end_date: date
    date_type: str
    metrics: Metrics


class Address(BaseModel):
    name: str
    address_one: str
    address_two: str | None
    city: str
    state: str
    zip: str
    note: str | None
    phone: str | None
    email: str | None


class HistoryEvent(LocalTimes):
    id: str
    action: str
    event_time: datetime
    receipt_order: str


class ShipmentDetail(TrackingRow):
    sender: Address
    recipient: Address
    history: list[HistoryEvent]
    notes: str | None
    order_date: date | None
    created_at: datetime
    pod_url: str | None = None
