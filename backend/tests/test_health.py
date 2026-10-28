from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import PostgresDsn, RedisDsn, SecretStr, ValidationError

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        database_url=PostgresDsn("postgresql://test:private@localhost/test"),
        redis_url=RedisDsn("redis://localhost:6379/0"),
        auth_secret=SecretStr("synthetic-test-key-" * 4),
        app_env="test",
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_liveness_does_not_require_dependencies(client: TestClient) -> None:
    with patch("app.main.check_postgres", side_effect=AssertionError):
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("database_down", "redis_down"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_readiness(client: TestClient, database_down: bool, redis_down: bool) -> None:
    with (
        patch("app.main.check_postgres", new_callable=AsyncMock) as postgres,
        patch("app.main.check_redis", new_callable=AsyncMock) as redis,
    ):
        if database_down:
            postgres.side_effect = RuntimeError("secret database credentials")
        if redis_down:
            redis.side_effect = TimeoutError("secret redis credentials")
        response = client.get("/health/ready")
    assert response.status_code == (503 if database_down or redis_down else 200)
    assert response.json() == {
        "status": "unavailable" if database_down or redis_down else "ok",
        "dependencies": {
            "postgres": "unavailable" if database_down else "ok",
            "redis": "unavailable" if redis_down else "ok",
        },
    }
    assert "secret" not in response.text


def test_configuration_rejects_non_utc_reporting() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url=PostgresDsn("postgresql://test:private@localhost/test"),
            redis_url=RedisDsn("redis://localhost:6379/0"),
            auth_secret=SecretStr("synthetic-test-key-" * 4),
            app_env="test",
            app_timezone="America/Los_Angeles",
        )
