"""domain.password_reset — token generation/hashing pure functions (SoT A5.1)."""

from __future__ import annotations

from src.domain.password_reset import generate_reset_token, hash_reset_token


def test_generate_reset_token_is_unique_per_call() -> None:
    assert generate_reset_token() != generate_reset_token()


def test_hash_reset_token_never_equals_the_raw_token() -> None:
    token = generate_reset_token()

    assert hash_reset_token(token) != token


def test_hash_reset_token_is_deterministic() -> None:
    token = generate_reset_token()

    assert hash_reset_token(token) == hash_reset_token(token)


def test_hash_reset_token_varies_by_token() -> None:
    assert hash_reset_token("token-a") != hash_reset_token("token-b")
