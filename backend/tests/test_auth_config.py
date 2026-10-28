import uuid
from typing import cast
from unittest.mock import Mock

import pytest
from pydantic import PostgresDsn, RedisDsn, SecretStr, ValidationError
from redis import Redis
from redis.exceptions import ConnectionError

from app.auth.limiter import LimiterUnavailable, RedisLoginLimiter
from app.config import Settings


def test_production_requires_https_origins_and_long_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url=PostgresDsn("postgresql://test:test@localhost/test"),
            redis_url=RedisDsn("redis://localhost"),
            auth_secret=SecretStr("short"),
        )
    with pytest.raises(ValidationError):
        Settings(
            database_url=PostgresDsn("postgresql://test:test@localhost/test"),
            redis_url=RedisDsn("redis://localhost"),
            auth_secret=SecretStr("synthetic" * 8),
            app_env="production",
            auth_allowed_origins=["http://localhost:5173"],
        )


def test_limiter_fails_closed_without_exposing_redis_errors() -> None:
    client = Mock(spec=Redis)
    client.eval.side_effect = ConnectionError("sensitive connection info")
    with pytest.raises(LimiterUnavailable) as error:
        RedisLoginLimiter(client, "synthetic").allow("test-ip", "test-identity")
    assert "sensitive" not in str(error.value)


@pytest.mark.integration
def test_real_redis_limiter_uses_atomic_private_keys(migrated_database: object) -> None:
    # Database fixture provides the opt-in guard and isolated environment.
    client = Redis.from_url("redis://redis:6379/0", socket_timeout=2)
    prefix = "test:auth:" + uuid.uuid4().hex
    limiter = RedisLoginLimiter(client, "synthetic-test-secret", prefix)
    try:
        assert all(limiter.allow("test-ip", "private@example.test") for _ in range(10))
        assert not limiter.allow("test-ip", "private@example.test")
        assert not limiter.allow("other-ip", "private@example.test")
        keys = list(client.scan_iter(match=prefix + ":*"))
        assert all(b"private@example.test" not in key for key in keys)
        assert all(0 < cast(int, client.ttl(key)) <= 60 for key in keys)
        assert all(limiter.allow("test-ip-2", str(index)) for index in range(30))
        assert not limiter.allow("test-ip-2", "another-identity")
    finally:
        keys = list(client.scan_iter(match=prefix + ":*"))
        if keys:
            client.delete(*keys)
        client.close()
