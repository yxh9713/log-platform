"""P10 due-today contracts; reporting date is server-derived UTC."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.shipments.query_dto import Metrics


class Exceptions(BaseModel):
    attempted: int
    returned: int
    void: int
    consolidated: Literal[0] = 0
    no_package: Literal[0] = 0
    held: Literal[0] = 0


class DayStats(Metrics):
    report_date: date


class ExceptionStats(Exceptions):
    report_date: date


class AreaStats(Metrics):
    id: int
    area: str


class AreaStatsResponse(BaseModel):
    report_date: date
    items: list[AreaStats]


class DayReport(BaseModel):
    report_date: date
    stats: Metrics
    exceptions: Exceptions
    areas: list[AreaStats]
