from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dto import LoginInput, MessageResponse, Principal, TokenResponse
from app.auth.limiter import LimiterUnavailable
from app.auth.service import (
    SESSION_SECONDS,
    AuthService,
    InvalidLogin,
    InvalidSession,
    LoginLimited,
)
from app.config import Settings

COOKIE_NAME = "logistics_session"
router = APIRouter(prefix="/v1", tags=["session"])
bearer_scheme = HTTPBearer(auto_error=False)
cookie_scheme = APIKeyCookie(name=COOKIE_NAME, auto_error=False)
AUTH_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": MessageResponse, "description": "Authentication required"},
    403: {"model": MessageResponse, "description": "Origin or permission denied"},
    503: {"model": MessageResponse, "description": "Authentication unavailable"},
}


def service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth)


def browser_origin(request: Request) -> None:
    config = cast(Settings, request.app.state.config)
    origin = request.headers.get("origin")
    if origin is not None and origin not in config.auth_allowed_origins:
        raise HTTPException(403, "Origin is not allowed")


def request_token(
    request: Request,
    bearer: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_scheme)
    ] = None,
    cookie: Annotated[str | None, Security(cookie_scheme)] = None,
) -> str:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or " " in token:
            raise HTTPException(401, "Authentication required")
        return token
    cookie_token = request.cookies.get(COOKIE_NAME)
    if not cookie_token:
        raise HTTPException(401, "Authentication required")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        browser_origin(request)
        if request.headers.get("x-requested-with") != "logistics-web":
            raise HTTPException(403, "Request header required")
    return cookie_token


def current_user(
    request: Request, token: Annotated[str, Depends(request_token)]
) -> Principal:
    try:
        principal = service(request).authenticate(token)
        request.state.principal = principal
        return principal
    except InvalidSession:
        raise HTTPException(401, "Authentication required") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Authentication is temporarily unavailable") from None


def require_administrator(
    principal: Annotated[Principal, Depends(current_user)],
) -> Principal:
    if principal.role != "administrator":
        raise HTTPException(403, "Administrator role required")
    return principal


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        **AUTH_ERRORS,
        413: {"model": MessageResponse, "description": "Body exceeds 8 KiB"},
        415: {"model": MessageResponse, "description": "JSON required"},
        422: {"model": MessageResponse, "description": "Invalid login input"},
        429: {"model": MessageResponse, "description": "Login limit exceeded"},
    },
)
def login(payload: LoginInput, request: Request, response: Response) -> TokenResponse:
    browser_origin(request)
    if (
        request.headers.get("content-type", "").split(";")[0].strip()
        != "application/json"
    ):
        raise HTTPException(415, "JSON content type required")
    try:
        result = service(request).login(
            payload, request.client.host if request.client else "unknown"
        )
    except InvalidLogin:
        raise HTTPException(401, "Invalid credentials") from None
    except LoginLimited:
        raise HTTPException(
            429,
            "Too many login attempts. Try again in one minute.",
            headers={"Retry-After": "60"},
        ) from None
    except (LimiterUnavailable, SQLAlchemyError):
        raise HTTPException(503, "Authentication is temporarily unavailable") from None
    config = cast(Settings, request.app.state.config)
    response.set_cookie(
        COOKIE_NAME,
        result.token,
        max_age=SESSION_SECONDS,
        path="/v1",
        httponly=True,
        secure=config.app_env == "production",
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(token=result.token)


@router.get("/session", response_model=Principal, responses=AUTH_ERRORS)
def session(
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
) -> Principal:
    response.headers["Cache-Control"] = "no-store"
    return principal


@router.post("/logout", response_model=MessageResponse, responses=AUTH_ERRORS)
def logout(
    request: Request, response: Response, token: Annotated[str, Depends(request_token)]
) -> MessageResponse:
    try:
        service(request).logout(token)
    except InvalidSession:
        # Clear an expired/invalid cookie too; a malformed token grants no access.
        pass
    except SQLAlchemyError:
        raise HTTPException(503, "Authentication is temporarily unavailable") from None
    response.delete_cookie(
        COOKIE_NAME,
        path="/v1",
        httponly=True,
        secure=cast(Settings, request.app.state.config).app_env == "production",
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return MessageResponse(message="Signed out")
