from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dto import Principal
from app.auth.routes import current_user
from app.shipments.common import DomainError
from app.shipments.day import DayService
from app.shipments.day_dto import AreaStatsResponse, DayReport, DayStats, ExceptionStats
from app.shipments.routes import ERRORS

router = APIRouter(prefix="/v1", tags=["My Day statistics"])


def read_day(request: Request, response: Response, principal: Principal) -> DayReport:
    if request.query_params:
        raise DomainError(422, "My Day statistics accept no query parameters")
    response.headers["Cache-Control"] = "no-store"
    try:
        return cast(DayService, request.app.state.day).my_day(principal)
    except SQLAlchemyError:
        raise DomainError(
            503, "My Day statistics are temporarily unavailable"
        ) from None


@router.get("/my-day", response_model=DayReport, responses=ERRORS)
def my_day(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> DayReport:
    return read_day(request, response, principal)


@router.get("/shipment-stats", response_model=DayStats, responses=ERRORS)
def shipment_stats(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> DayStats:
    day = read_day(request, response, principal)
    return DayStats(report_date=day.report_date, **day.stats.model_dump())


@router.get("/exceptions-stats", response_model=ExceptionStats, responses=ERRORS)
def exception_stats(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> ExceptionStats:
    day = read_day(request, response, principal)
    return ExceptionStats(report_date=day.report_date, **day.exceptions.model_dump())


@router.get("/area-stats", response_model=AreaStatsResponse, responses=ERRORS)
def area_stats(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> AreaStatsResponse:
    day = read_day(request, response, principal)
    return AreaStatsResponse(report_date=day.report_date, items=day.areas)
