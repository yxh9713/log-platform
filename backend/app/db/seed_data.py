"""Editable development declarations. Never put passwords or sample packages here."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CompanySeed:
    name: str
    slug: str
    company_type: Literal[1, 2]


@dataclass(frozen=True)
class UserSeed:
    company_slug: str
    email: str
    role: str


@dataclass(frozen=True)
class SeedData:
    companies: tuple[CompanySeed, ...]
    roles: tuple[str, ...]
    actions: tuple[str, ...]
    users: tuple[UserSeed, ...]


DEVELOPMENT_DATA = SeedData(
    companies=(
        CompanySeed("Paychex", "paychex", 2),
        CompanySeed("OnTrac", "ontrac", 1),
    ),
    roles=("administrator", "user"),
    actions=(
        "created",
        "picked up",
        "possession",
        "out for delivery",
        "delivered",
        "attempted",
        "returned",
    ),
    users=(
        UserSeed("paychex", "admin@paychex.example", "administrator"),
        UserSeed("paychex", "user@paychex.example", "user"),
    ),
)
