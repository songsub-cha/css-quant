from __future__ import annotations

from src.domain.security import hash_password, verify_password


def test_hash_password_produces_argon2id_hash() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed.startswith("$argon2id$")
    assert hashed != "correct horse battery staple"


def test_verify_password_accepts_the_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_an_incorrect_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_a_malformed_hash() -> None:
    assert verify_password("anything", "not-a-real-argon2-hash") is False
