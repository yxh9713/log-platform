from app.passwords import hash_password, verify_password


def test_argon2id_round_trip_and_salts() -> None:
    password = "synthetic test password only"
    first = hash_password(password)
    second = hash_password(password)
    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password(password, first)
    assert not verify_password("wrong password", first)
    assert not verify_password(password, "invalid hash")
