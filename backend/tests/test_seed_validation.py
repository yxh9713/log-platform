from dataclasses import replace

import pytest

from app.db.seed import InitialCredential, SeedResult, validate_data
from app.db.seed_data import DEVELOPMENT_DATA, UserSeed


def test_required_declarations_are_valid() -> None:
    validate_data(DEVELOPMENT_DATA)
    assert {item.slug for item in DEVELOPMENT_DATA.companies} == {"paychex", "ontrac"}
    assert len(DEVELOPMENT_DATA.users) == 2


@pytest.mark.parametrize(
    "users",
    [
        (UserSeed("missing", "admin@paychex.example", "administrator"),),
        (UserSeed("paychex", "admin@paychex.example", "missing"),),
        (UserSeed("paychex", "Admin@paychex.example", "administrator"),),
        (UserSeed("paychex", "invalid", "administrator"),),
        (DEVELOPMENT_DATA.users[0], DEVELOPMENT_DATA.users[0]),
    ],
)
def test_invalid_declarations_are_rejected(users: tuple[UserSeed, ...]) -> None:
    with pytest.raises(ValueError):
        validate_data(replace(DEVELOPMENT_DATA, users=users))


def test_generated_secrets_are_not_in_result_representations() -> None:
    secret = "synthetic secret only"
    credential = InitialCredential("paychex", "admin@paychex.example", secret)
    assert secret not in repr(credential)
    assert secret not in repr(SeedResult(credentials=[credential]))
