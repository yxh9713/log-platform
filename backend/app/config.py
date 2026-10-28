from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: PostgresDsn
    app_timezone: Literal["UTC"] = "UTC"
    app_env: Literal["development", "test", "production"] = "production"


class Settings(DatabaseSettings):
    export_root: Path = Path("/data/exports")
    redis_url: RedisDsn

    auth_secret: SecretStr = Field(min_length=32)
    auth_allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    @model_validator(mode="after")
    def production_origins(self) -> "Settings":
        if self.app_env == "production" and (
            not self.auth_allowed_origins
            or any(
                not origin.startswith("https://")
                for origin in self.auth_allowed_origins
            )
        ):
            raise ValueError("Production requires explicit HTTPS auth origins")
        return self
