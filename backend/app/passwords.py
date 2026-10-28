"""Shared Argon2id hashing/verifier for seeding and the future login slice."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False
