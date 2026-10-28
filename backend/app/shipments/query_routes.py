from collections.abc import Callable
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dto import MessageResponse, Principal
from app.auth.routes import browser_origin, current_user
from app.exports.dto import ExportAccepted
from app.exports.service import ExportService
from app.shipments.common import DomainError
from app.shipments.queries import QueryService
from app.shipments.query_dto import (
    SearchQuery,
    SearchResult,
    ShipmentDetail,
    TrackingQuery,
    TrackingResult,
)
from app.shipments.routes import ERRORS

router = APIRouter(prefix="/v1/shipments", tags=["shipment queries"])


def read[T](
    request: Request, response: Response, operation: Callable[[QueryService], T]
) -> T:
    # Prevent silent last-value wins for singleton filter parameters.
    for key in request.query_params:
        if key != "area" and len(request.query_params.getlist(key)) > 1:
            raise DomainError(422, "Repeated query parameter")
    response.headers["Cache-Control"] = "no-store"
    try:
        return operation(cast(QueryService, request.app.state.queries))
    except SQLAlchemyError:
        raise DomainError(503, "Shipment queries are temporarily unavailable") from None


@router.get(
    "",
    response_model=TrackingResult | ExportAccepted,
    responses={
        **ERRORS,
        202: {"model": ExportAccepted},
        429: {"model": MessageResponse, "description": "Requester queue limit"},
    },
)
def tracking(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
    query: Annotated[TrackingQuery, Query()],
) -> TrackingResult | ExportAccepted:
    if query.export == 1:
        browser_origin(request)
        if (
            "authorization" not in request.headers
            and request.headers.get("x-requested-with") != "logistics-web"
        ):
            raise DomainError(403, "Request header required")
        if "page" in request.query_params or "length" in request.query_params:
            raise DomainError(422, "Export accepts no pagination")
        # Reuse singleton validation and sanitized infrastructure handling.
        read(
            request,
            response,
            lambda unused: cast(ExportService, request.app.state.exports).accept(
                principal, query
            ),
        )
        response.status_code = 202
        return ExportAccepted()
    return read(request, response, lambda service: service.tracking(principal, query))


@router.get("/search", response_model=SearchResult, responses=ERRORS)
def search(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
    query: Annotated[SearchQuery, Query()],
) -> SearchResult:
    return read(request, response, lambda service: service.search(principal, query))


@router.get("/{shipment_id}", response_model=ShipmentDetail, responses=ERRORS)
def detail(
    shipment_id: Annotated[int, Path(ge=1, le=9223372036854775807)],
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> ShipmentDetail:
    if request.query_params:
        raise DomainError(422, "Detail accepts only a stable package ID")
    return read(
        request, response, lambda service: service.detail(principal, shipment_id)
    )
