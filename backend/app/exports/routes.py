import asyncio
from collections.abc import AsyncGenerator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.auth.dto import MessageResponse, Principal
from app.auth.routes import browser_origin, current_user, request_token
from app.auth.service import AuthService, InvalidSession
from app.config import Settings
from app.exports.dto import ExportList, ExportStatus
from app.exports.service import ExportService, status
from app.exports.storage import open_download
from app.shipments.common import DomainError
from app.shipments.routes import ERRORS

router = APIRouter(prefix="/v1/exports", tags=["exports"])


def service(request: Request) -> ExportService:
    return cast(ExportService, request.app.state.exports)


def no_query(request: Request) -> None:
    if request.query_params:
        raise DomainError(422, "Export endpoints accept no query parameters")


async def stream(request: Request, token: str) -> AsyncGenerator[str, None]:
    previous: str | None = None
    yield "retry: 3000\n\n"
    while not await request.is_disconnected():
        try:
            # Recheck expiry, revocation and current membership for an open stream.
            principal = await run_in_threadpool(
                cast(AuthService, request.app.state.auth).authenticate, token
            )
            report = await run_in_threadpool(service(request).list, principal)
            payload = report.model_dump_json()
            if payload != previous:
                yield "event: exports\ndata: " + payload + "\n\n"
                previous = payload
            else:
                yield "event: heartbeat\ndata: {}\n\n"
        except (InvalidSession, DomainError):
            yield "event: session-expired\ndata: {}\n\n"
            return
        except SQLAlchemyError:
            yield "event: unavailable\ndata: {}\n\n"
            return
        await asyncio.sleep(2)


@router.get("", response_model=ExportList, responses=ERRORS)
def exports(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> ExportList:
    no_query(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return service(request).list(principal)
    except SQLAlchemyError:
        raise DomainError(503, "Exports are temporarily unavailable") from None


@router.get(
    "/events",
    response_class=StreamingResponse,
    responses={**ERRORS, 200: {"content": {"text/event-stream": {}}}},
)
def events(
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    token: Annotated[str, Depends(request_token)],
) -> StreamingResponse:
    no_query(request)
    browser_origin(request)
    return StreamingResponse(
        stream(request, token),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/{identity}", response_model=ExportStatus, responses=ERRORS)
def export_status(
    identity: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> ExportStatus:
    no_query(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return status(service(request).get(principal, str(identity)))
    except SQLAlchemyError:
        raise DomainError(503, "Exports are temporarily unavailable") from None


@router.post("/{identity}/dismiss", response_model=MessageResponse, responses=ERRORS)
def dismiss(
    identity: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> MessageResponse:
    no_query(request)
    try:
        service(request).dismiss(principal, str(identity))
    except SQLAlchemyError:
        raise DomainError(503, "Exports are temporarily unavailable") from None
    response.headers["Cache-Control"] = "no-store"
    return MessageResponse(message="Export dismissed")


@router.get(
    "/{identity}/download",
    response_class=StreamingResponse,
    responses={
        **ERRORS,
        409: {"model": MessageResponse},
        200: {"content": {"text/csv": {}}},
    },
)
def download(
    identity: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
) -> StreamingResponse:
    no_query(request)
    try:
        job = service(request).get(principal, str(identity))
    except SQLAlchemyError:
        raise DomainError(503, "Exports are temporarily unavailable") from None
    if job["state"] != "ready":
        raise DomainError(409, "Export is not ready")
    data = open_download(
        cast(Settings, request.app.state.config).export_root,
        str(identity),
        job["filename"],
        job["size_bytes"],
    )
    return StreamingResponse(
        data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{job["filename"]}"',
            "Content-Length": str(job["size_bytes"]),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
