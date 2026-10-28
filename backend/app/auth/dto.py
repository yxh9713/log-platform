from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(min_length=3, max_length=320)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=1024)]
    slug: Annotated[str, Field(min_length=1, max_length=64)]

    @field_validator("email", "slug", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str) -> str:
        if (
            value.count("@") != 1
            or not all(value.split("@"))
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Invalid email")
        return value

    @field_validator("password")
    @classmethod
    def password_nonblank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Password is required")
        return value


class TokenResponse(BaseModel):
    token: str


class CompanyIdentity(BaseModel):
    id: str
    name: str
    slug: str


class Principal(BaseModel):
    id: str
    email: str
    role: Literal["administrator", "user"]
    company: CompanyIdentity
    expires_at: datetime


class MessageResponse(BaseModel):
    message: str
