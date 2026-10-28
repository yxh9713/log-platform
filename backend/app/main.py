import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.auth.body_limit import LoginBodyLimit
from app.auth.dto import Principal
from app.auth.limiter import RedisLoginLimiter
from app.auth.routes import request_token, router
from app.auth.service import AuthService, InvalidSession
from app.carriers.routes import router as carrier_router
from app.carriers.service import CarrierService
from app.config import Settings
from app.db.connection import create_database_engine
from app.exports.routes import router as export_router
from app.exports.service import ExportService
from app.shipments.areas import AreaService
from app.shipments.common import DomainError
from app.shipments.day import DayService
from app.shipments.day_routes import router as day_router
from app.shipments.queries import QueryService
from app.shipments.query_routes import router as query_router
from app.shipments.routes import router as shipment_router
from app.shipments.service import ShipmentService


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class Dependencies(BaseModel):
    postgres: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


class Readiness(BaseModel):
    status: Literal["ok", "unavailable"]
    dependencies: Dependencies


async def check_postgres(settings: Settings) -> None:
    async with await psycopg.AsyncConnection.connect(
        str(settings.database_url), connect_timeout=2, options="-c timezone=UTC"
    ) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1")
            if await cursor.fetchone() != (1,):
                raise RuntimeError("Unexpected database response")


async def check_redis(settings: Settings) -> None:
    async with Redis.from_url(
        str(settings.redis_url), socket_connect_timeout=2, socket_timeout=2
    ) as client:
        if not await client.ping():
            raise RuntimeError("Unexpected Redis response")


async def probe(check: Callable[[], Awaitable[None]]) -> Literal["ok", "unavailable"]:
    try:
        async with asyncio.timeout(3):
            await check()
    except Exception:
        # Health responses must not expose connection strings or exception details.
        return "unavailable"
    return "ok"


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    engine = create_database_engine(config)
    redis_client = SyncRedis.from_url(
        str(config.redis_url), socket_connect_timeout=2, socket_timeout=2
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()
            redis_client.close()

    app = FastAPI(title="Logistics API", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.auth = AuthService(
        engine,
        config.auth_secret.get_secret_value(),
        RedisLoginLimiter(redis_client, config.auth_secret.get_secret_value()).allow,
    )
    app.state.shipments = ShipmentService(engine)
    app.state.areas = AreaService(engine)
    app.state.queries = QueryService(engine)
    app.state.day = DayService(engine)
    app.state.exports = ExportService(engine)
    app.state.carriers = CarrierService(engine)
    app.include_router(router)
    app.include_router(shipment_router)
    app.include_router(query_router)
    app.include_router(day_router)
    app.include_router(export_router)
    app.include_router(carrier_router)
    app.add_middleware(LoginBodyLimit)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            {"message": str(error.detail)},
            status_code=error.status_code,
            headers={**(error.headers or {}), "Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # Diagnostics deliberately omit submitted address/contact/credential data.
        status, message, code = 422, "Invalid request", "invalid_input"
        if request.url.path == "/v1/login":
            message = "Check email, password and company slug."
        elif request.url.path == "/v1/shipments" and request.method == "POST":
            message = "Invalid shipment request"
            body = error.body
            if isinstance(body, dict):

                def identifier(value: object) -> str | None:
                    return (
                        value.strip()
                        if isinstance(value, str) and len(value) <= 255
                        else None
                    )

                request.state.creation_identity = (
                    identifier(body.get("reference")),
                    identifier(body.get("account_number")),
                )
                account = body.get("account_number")
                if account is None or isinstance(account, str) and not account.strip():
                    status, message, code = (
                        400,
                        "account is required",
                        "missing_account",
                    )
                elif any(
                    item["loc"][:2]
                    in (("body", "account_number"), ("body", "carrier_id"))
                    for item in error.errors()
                ):
                    status, message, code = (
                        400,
                        "Invalid service or account",
                        "invalid_assignment",
                    )
            failure = await persist_creation_error(request, code)
            if failure is not None:
                status, message = failure.status, failure.message
        elif request.url.path.startswith("/v1/area"):
            message = "Invalid area request"
        return JSONResponse(
            {"message": message},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    async def persist_creation_error(request: Request, code: str) -> DomainError | None:
        principal = getattr(request.state, "principal", None)
        if request.url.path != "/v1/shipments" or request.method != "POST":
            return None
        if not isinstance(principal, Principal):
            try:
                token = request_token(request)
                principal = await run_in_threadpool(app.state.auth.authenticate, token)
            except HTTPException as error:
                return DomainError(error.status_code, str(error.detail))
            except InvalidSession:
                return DomainError(401, "Authentication required")
            except SQLAlchemyError:
                return DomainError(503, "Authentication is temporarily unavailable")
        try:
            reference, account = getattr(
                request.state, "creation_identity", (None, None)
            )
            await run_in_threadpool(
                app.state.shipments.record_error, principal, code, reference, account
            )
        except DomainError as error:
            return error
        except SQLAlchemyError:
            return DomainError(503, "Shipment diagnostics are temporarily unavailable")
        return None

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        if error.status in (400, 422):
            diagnostic_failure = await persist_creation_error(request, error.code)
            if diagnostic_failure is not None:
                error = diagnostic_failure
        return JSONResponse(
            {"message": error.message},
            status_code=error.status,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health/live", response_model=Liveness)
    async def live() -> Liveness:
        return Liveness()

    @app.get("/health/ready", response_model=Readiness)
    async def ready(response: Response) -> Readiness:
        postgres, redis = await asyncio.gather(
            probe(lambda: check_postgres(config)), probe(lambda: check_redis(config))
        )
        healthy = postgres == redis == "ok"
        response.status_code = 200 if healthy else 503
        return Readiness(
            status="ok" if healthy else "unavailable",
            dependencies=Dependencies(postgres=postgres, redis=redis),
        )

    return app
