from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import PostgresDsn, RedisDsn, SecretStr
from sqlalchemy import Engine

from app.auth.dto import Principal
from app.auth.routes import require_administrator
from app.auth.service import SESSION_SECONDS, AuthService
from app.config import Settings
from app.db.schema import auth_sessions, company, user_role, users
from app.db.seed import seed_database
from app.main import create_app
from app.passwords import hash_password

pytestmark = pytest.mark.integration


class TestPasswords(dict[str, str]):
    __test__ = False

    def __repr__(self) -> str:
        return "<synthetic passwords redacted>"


@pytest.fixture
def auth_client(
    migrated_database: Engine,
) -> Iterator[tuple[TestClient, dict[str, str], Engine]]:
    result = seed_database(migrated_database)
    passwords = TestPasswords(
        {item.email: item.password for item in result.credentials}
    )
    settings = Settings(
        database_url=PostgresDsn(
            migrated_database.url.set(drivername="postgresql").render_as_string(
                hide_password=False
            )
        ),
        redis_url=RedisDsn("redis://redis:6379/0"),
        app_env="test",
        auth_secret=SecretStr("synthetic-auth-test-key-" * 3),
    )
    app = create_app(settings)
    app.state.auth = AuthService(
        migrated_database,
        settings.auth_secret.get_secret_value(),
        lambda ip, identity: True,
    )

    @app.get("/v1/test/admin")
    def administrator_only(
        principal: Annotated[Principal, Depends(require_administrator)],
    ) -> dict[str, str]:
        return {"company_id": principal.company.id}

    with TestClient(app) as client:
        yield client, passwords, migrated_database


def login(
    client: TestClient, passwords: dict[str, str], email: str = "admin@paychex.example"
) -> str:
    response = client.post(
        "/v1/login",
        json={"email": email, "password": passwords[email], "slug": "paychex"},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"token"}
    return str(response.json()["token"])


def test_seeded_login_cookie_restore_logout_and_bearer_revocation(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    client, passwords, engine = auth_client
    token = login(client, passwords)
    cookie = client.cookies.get("logistics_session")
    assert cookie == token
    response = client.get("/v1/session")
    assert response.status_code == 200
    assert response.json()["role"] == "administrator"
    assert response.json()["company"]["slug"] == "paychex"
    assert response.headers["cache-control"] == "no-store"
    with engine.connect() as connection:
        row = connection.execute(sa.select(auth_sessions)).mappings().one()
        assert token not in row.values()
        assert len(row["token_hash"]) == 64
        assert row["expires_at"] - row["created_at"] == timedelta(
            seconds=SESSION_SECONDS
        )
    assert (
        client.get(
            "/v1/session", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 200
    )
    response = client.post(
        "/v1/logout", json={}, headers={"X-Requested-With": "logistics-web"}
    )
    assert response.status_code == 200
    assert "logistics_session" not in client.cookies
    assert (
        client.get(
            "/v1/session", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 401
    )
    assert client.get("/v1/session").status_code == 401


@pytest.mark.parametrize(
    "failure",
    [
        "password",
        "email",
        "slug",
        "disabled-user",
        "disabled-company",
        "carrier",
        "role",
    ],
)
def test_invalid_login_is_generic(
    auth_client: tuple[TestClient, dict[str, str], Engine], failure: str
) -> None:
    client, passwords, engine = auth_client
    payload = {
        "email": "admin@paychex.example",
        "password": passwords["admin@paychex.example"],
        "slug": "paychex",
    }
    if failure in ("password", "email", "slug"):
        payload[failure] = "unknown@example.test" if failure == "email" else "incorrect"
    else:
        with engine.begin() as connection:
            if failure == "disabled-user":
                connection.execute(users.update().values(active=False))
            elif failure == "disabled-company":
                connection.execute(company.update().values(active=False))
            elif failure == "carrier":
                connection.execute(
                    company.update()
                    .where(company.c.slug == "paychex")
                    .values(company_type=1)
                )
            else:
                connection.execute(
                    user_role.update()
                    .where(user_role.c.name == "administrator")
                    .values(name="unsupported")
                )
    response = client.post("/v1/login", json=payload)
    assert response.status_code == 401
    assert response.json() == {"message": "Invalid credentials"}
    assert "logistics_session" not in client.cookies


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "invalid", "password": "sensitive-value", "slug": "paychex"},
        {"email": "admin@paychex.example", "password": "", "slug": "paychex"},
        {"email": "admin@paychex.example", "password": "sensitive-value", "slug": ""},
        {
            "email": "admin@paychex.example",
            "password": "sensitive-value",
            "slug": "paychex",
            "role": "administrator",
        },
        {
            "email": "admin@paychex.example",
            "password": "sensitive-value",
            "slug": "paychex",
            "company_id": 2,
        },
    ],
)
def test_input_errors_do_not_echo_password(
    auth_client: tuple[TestClient, dict[str, str], Engine], payload: dict[str, object]
) -> None:
    client, _, _ = auth_client
    response = client.post("/v1/login", json=payload)
    assert response.status_code == 422
    assert "sensitive-value" not in response.text
    assert response.json() == {"message": "Check email, password and company slug."}


def test_tenant_identity_is_from_database_and_role_rechecked(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    client, passwords, engine = auth_client
    token = login(client, passwords, "user@paychex.example")
    assert client.get("/v1/test/admin").status_code == 403
    with engine.begin() as connection:
        other_company = connection.execute(
            company.insert()
            .values(name="Test shipper", slug="test-shipper", company_type=2)
            .returning(company.c.id)
        ).scalar_one()
        role_id = connection.execute(
            sa.select(user_role.c.id).where(user_role.c.name == "administrator")
        ).scalar_one()
        connection.execute(
            users.insert().values(
                company_id=other_company,
                role_id=role_id,
                email="user@paychex.example",
                password=hash_password("other synthetic password"),
            )
        )
    response = client.get(
        f"/v1/session?company_id={other_company}&role=administrator",
        headers={"X-Company-ID": str(other_company), "X-Role": "administrator"},
    )
    assert response.json()["company"]["slug"] == "paychex"
    assert response.json()["role"] == "user"
    assert (
        client.post(
            "/v1/login",
            json={
                "email": "user@paychex.example",
                "password": passwords["user@paychex.example"],
                "slug": "test-shipper",
            },
        ).status_code
        == 401
    )
    with engine.begin() as connection:
        connection.execute(
            users.update()
            .where(
                users.c.email == "user@paychex.example",
                users.c.company_id != other_company,
            )
            .values(role_id=role_id)
        )
    assert (
        client.get(
            "/v1/test/admin", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 200
    )
    with engine.begin() as connection:
        regular_role = connection.execute(
            sa.select(user_role.c.id).where(user_role.c.name == "user")
        ).scalar_one()
        connection.execute(users.update().values(role_id=regular_role))
    assert client.get("/v1/test/admin").status_code == 403


@pytest.mark.parametrize("change", ["user", "company", "type"])
def test_current_session_rechecks_active_membership(
    auth_client: tuple[TestClient, dict[str, str], Engine], change: str
) -> None:
    client, passwords, engine = auth_client
    login(client, passwords)
    with engine.begin() as connection:
        if change == "user":
            connection.execute(users.update().values(active=False))
        elif change == "company":
            connection.execute(company.update().values(active=False))
        else:
            connection.execute(
                company.update()
                .where(company.c.slug == "paychex")
                .values(company_type=1)
            )
    assert client.get("/v1/session").status_code == 401


def test_expiry_signature_revocation_and_no_token_in_urls(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    client, passwords, engine = auth_client
    token = login(client, passwords)
    client.cookies.clear()
    assert client.get("/v1/session?token=" + token).status_code == 401
    assert (
        client.get(
            "/v1/session", headers={"Authorization": "Bearer " + token + "tampered"}
        ).status_code
        == 401
    )
    with patch(
        "itsdangerous.timed.time.time",
        return_value=datetime.now(UTC).timestamp() + SESSION_SECONDS + 1,
    ):
        assert (
            client.get(
                "/v1/session", headers={"Authorization": "Bearer " + token}
            ).status_code
            == 401
        )
    with engine.begin() as connection:
        connection.execute(
            auth_sessions.update().values(
                created_at=datetime.now(UTC) - timedelta(hours=10),
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
    assert (
        client.get(
            "/v1/session", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 401
    )


def test_cookie_csrf_and_token_precedence(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    client, passwords, _ = auth_client
    token = login(client, passwords)
    assert client.post("/v1/logout", json={}).status_code == 403
    assert (
        client.post(
            "/v1/logout",
            json={},
            headers={
                "X-Requested-With": "logistics-web",
                "Origin": "https://untrusted.example",
            },
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/v1/session", headers={"Authorization": "Basic invalid"}
        ).status_code
        == 401
    )
    assert client.get("/v1/session").status_code == 200
    assert (
        client.post(
            "/v1/logout", json={}, headers={"Authorization": "Bearer " + token}
        ).status_code
        == 200
    )


def test_login_origin_and_cookie_flags(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    client, passwords, _ = auth_client
    payload = {
        "email": "admin@paychex.example",
        "password": passwords["admin@paychex.example"],
        "slug": "paychex",
    }
    assert (
        client.post(
            "/v1/login", json=payload, headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    response = client.post(
        "/v1/login", json=payload, headers={"Origin": "http://localhost:5173"}
    )
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/v1" in cookie
    assert "Max-Age=28800" in cookie
    assert response.headers["cache-control"] == "no-store"
    cast(FastAPI, client.app).state.config.app_env = "production"
    response = client.post("/v1/login", json=payload)
    assert "Secure" in response.headers["set-cookie"]


def test_login_rate_limit_and_service_errors_are_sanitized(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    from app.auth.limiter import LimiterUnavailable

    client, passwords, _ = auth_client
    payload = {
        "email": "admin@paychex.example",
        "password": passwords["admin@paychex.example"],
        "slug": "paychex",
    }
    with patch.object(
        cast(FastAPI, client.app).state.auth, "allow_login", return_value=False
    ):
        response = client.post("/v1/login", json=payload)
        assert response.status_code == 429 and response.headers["retry-after"] == "60"
    with patch.object(
        cast(FastAPI, client.app).state.auth,
        "allow_login",
        side_effect=LimiterUnavailable,
    ):
        response = client.post("/v1/login", json=payload)
        assert response.status_code == 503
        assert response.json() == {
            "message": "Authentication is temporarily unavailable"
        }


def test_login_bounded_body_and_key_rotation(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    client, passwords, engine = auth_client
    response = client.post(
        "/v1/login", content=b"x" * 8193, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert "x" * 100 not in response.text
    token = login(client, passwords)
    app = cast(FastAPI, client.app)
    app.state.auth = AuthService(
        engine, "rotated synthetic test key" * 3, lambda ip, identity: True
    )
    assert (
        client.get(
            "/v1/session", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 401
    )


@pytest.mark.parametrize("endpoint", ["login", "session", "logout"])
def test_database_auth_errors_fail_closed(
    auth_client: tuple[TestClient, dict[str, str], Engine], endpoint: str
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    client, passwords, _ = auth_client
    login(client, passwords)
    method = "authenticate" if endpoint == "session" else endpoint
    auth = cast(FastAPI, client.app).state.auth
    with patch.object(
        auth, method, side_effect=SQLAlchemyError("private connection info")
    ):
        if endpoint == "session":
            response = client.get("/v1/session")
        elif endpoint == "logout":
            response = client.post(
                "/v1/logout", json={}, headers={"X-Requested-With": "logistics-web"}
            )
        else:
            response = client.post(
                "/v1/login",
                json={
                    "email": "admin@paychex.example",
                    "password": passwords["admin@paychex.example"],
                    "slug": "paychex",
                },
            )
    assert response.status_code == 503
    assert response.json() == {"message": "Authentication is temporarily unavailable"}
    assert "private" not in response.text


def test_auth_openapi_matches_transport(
    auth_client: tuple[TestClient, dict[str, str], Engine],
) -> None:
    client, _, _ = auth_client
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/v1/login"]["post"]["responses"]) == {
        "200",
        "401",
        "403",
        "413",
        "415",
        "422",
        "429",
        "503",
    }
    assert schema["paths"]["/v1/session"]["get"]["security"] == [
        {"HTTPBearer": []},
        {"APIKeyCookie": []},
    ]
    assert schema["paths"]["/v1/login"]["post"].get("security") is None
