from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dto import MessageResponse, Principal
from app.auth.routes import current_user, require_administrator
from app.shipments.areas import AreaService
from app.shipments.common import DomainError
from app.shipments.dto import AreaInput, AreaOutput, ShipmentCreated, ShipmentInput
from app.shipments.service import ShipmentService

router = APIRouter(prefix="/v1", tags=["creation and areas"])
ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": MessageResponse} for status in (400, 401, 403, 404, 422, 503)
}
AreaId = Annotated[int, Path(ge=1, le=9223372036854775807)]


def shipments_service(request: Request) -> ShipmentService:
    return cast(ShipmentService, request.app.state.shipments)


def areas_service(request: Request) -> AreaService:
    return cast(AreaService, request.app.state.areas)


@router.post(
    "/shipments",
    response_model=ShipmentCreated,
    status_code=201,
    responses={
        **ERRORS,
        200: {"model": ShipmentCreated},
        413: {"model": MessageResponse},
    },
)
def create_shipment(
    payload: ShipmentInput,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> ShipmentCreated:
    request.state.creation_identity = (payload.reference, payload.account_number)
    try:
        result = shipments_service(request).create(principal, payload)
    except SQLAlchemyError:
        raise DomainError(
            503, "Shipment creation is temporarily unavailable", "database_unavailable"
        ) from None
    response.status_code = 201 if result.created else 200
    response.headers["Cache-Control"] = "no-store"
    return result.shipment


@router.get("/areas", response_model=list[AreaOutput], responses=ERRORS)
def list_areas(
    request: Request, principal: Annotated[Principal, Depends(current_user)]
) -> list[AreaOutput]:
    try:
        return areas_service(request).list(principal)
    except SQLAlchemyError:
        raise DomainError(503, "Areas are temporarily unavailable") from None


@router.post(
    "/area",
    response_model=AreaOutput,
    status_code=201,
    responses={**ERRORS, 200: {"model": AreaOutput}},
)
def create_area(
    payload: AreaInput,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_administrator)],
) -> AreaOutput:
    try:
        result, created = areas_service(request).create(principal, payload)
    except SQLAlchemyError:
        raise DomainError(503, "Areas are temporarily unavailable") from None
    response.status_code = 201 if created else 200
    return result


@router.put("/area/{id}", response_model=AreaOutput, responses=ERRORS)
def rename_area(
    id: AreaId,
    payload: AreaInput,
    request: Request,
    principal: Annotated[Principal, Depends(require_administrator)],
) -> AreaOutput:
    try:
        return areas_service(request).rename(principal, id, payload)
    except SQLAlchemyError:
        raise DomainError(503, "Areas are temporarily unavailable") from None


@router.delete("/area/{id}", response_model=MessageResponse, responses=ERRORS)
def delete_area(
    id: AreaId,
    request: Request,
    principal: Annotated[Principal, Depends(require_administrator)],
) -> MessageResponse:
    try:
        areas_service(request).delete(principal, id)
    except SQLAlchemyError:
        raise DomainError(503, "Areas are temporarily unavailable") from None
    return MessageResponse(message="Area deleted")
