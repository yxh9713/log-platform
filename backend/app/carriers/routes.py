"""Raw-ID, API-key-only carrier ingress with authentication before body parsing."""

import json
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.auth.dto import MessageResponse
from app.carriers.service import CarrierService
from app.integrations.carriers.ontrac.transformer import CarrierInput
from app.shipments.common import DomainError
from app.shipments.routes import ERRORS

router = APIRouter(tags=["carrier ingestion"])
api_key = APIKeyHeader(name="X-API-Key", auto_error=False)
MAX_WEBHOOK_BYTES = 7_000_000


class CarrierAcknowledgement(BaseModel):
    message: str
    outcome: Literal["accepted", "duplicate", "ignored"]
    receipt_id: str


def unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON field")
        result[key] = value
    return result


def invalid_constant(value: str) -> object:
    raise ValueError("Non-JSON constant")


@router.post(
    "/v1/webhook/{integrationId}",
    response_model=CarrierAcknowledgement,
    responses={
        **ERRORS,
        413: {"model": MessageResponse, "description": "Request too large"},
        415: {"model": MessageResponse, "description": "JSON content required"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": CarrierInput.model_json_schema(),
                }
            },
        }
    },
)
async def webhook(
    integrationId: str,
    request: Request,
    response: Response,
    key: Annotated[str | None, Depends(api_key)],
) -> CarrierAcknowledgement:
    service = cast(CarrierService, request.app.state.carriers)
    response.headers["Cache-Control"] = "no-store"
    try:
        if len(request.headers.getlist("X-API-Key")) != 1:
            raise DomainError(401, "Invalid API key", "invalid_api_key")
        await run_in_threadpool(service.authenticate, integrationId, key)
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise DomainError(415, "JSON content is required")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_WEBHOOK_BYTES:
                raise DomainError(413, "Carrier request is too large")
            chunks.append(chunk)
        try:
            values = json.loads(
                b"".join(chunks),
                object_pairs_hook=unique_json,
                parse_constant=invalid_constant,
            )
            if not isinstance(values, dict):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            raise DomainError(400, "Invalid carrier JSON") from None
        # Check the live verifier again after reading: key replacement during a
        # slow upload must not leave a previously cached authorization usable.
        receipt_id, result, error = await run_in_threadpool(
            service.receive, integrationId, key, values
        )
        if error:
            raise error
        if result.outcome == "rejected":
            raise DomainError(400, "Invalid carrier update")
        return CarrierAcknowledgement(
            message={
                "accepted": "Event accepted",
                "duplicate": "Duplicate event ignored",
                "ignored": "Unknown event ignored",
            }[result.outcome],
            outcome=result.outcome,
            receipt_id=receipt_id,
        )
    except SQLAlchemyError:
        raise DomainError(503, "Carrier ingestion is temporarily unavailable") from None
