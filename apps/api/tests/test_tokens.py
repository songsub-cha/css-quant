"""domain.tokens — access/refresh issuance and verification round-trips."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from src.domain.ids import generate_uuid7
from src.domain.tokens import (
    TokenType,
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_token,
)

_SECRET_KEY = "unit-test-secret-key-at-least-32-chars-long"


def test_access_token_round_trip() -> None:
    user_id = generate_uuid7()

    token = create_access_token(user_id, secret_key=_SECRET_KEY)

    assert decode_token(token, secret_key=_SECRET_KEY, expected_type=TokenType.ACCESS) == user_id


def test_refresh_token_round_trip() -> None:
    user_id = generate_uuid7()

    token = create_refresh_token(user_id, secret_key=_SECRET_KEY)

    assert decode_token(token, secret_key=_SECRET_KEY, expected_type=TokenType.REFRESH) == user_id


def test_create_token_pair_round_trips_both() -> None:
    user_id = generate_uuid7()

    pair = create_token_pair(user_id, secret_key=_SECRET_KEY)

    assert (
        decode_token(pair.access_token, secret_key=_SECRET_KEY, expected_type=TokenType.ACCESS)
        == user_id
    )
    assert (
        decode_token(pair.refresh_token, secret_key=_SECRET_KEY, expected_type=TokenType.REFRESH)
        == user_id
    )


def test_decode_rejects_wrong_secret_key() -> None:
    token = create_access_token(generate_uuid7(), secret_key=_SECRET_KEY)

    decoded = decode_token(
        token, secret_key="a-completely-different-secret-key", expected_type=TokenType.ACCESS
    )

    assert decoded is None


def test_decode_rejects_type_confusion() -> None:
    # A refresh token presented where an access token is expected (or vice
    # versa) must not verify — this is the type-confusion case
    # get_current_user relies on to reject a stolen refresh cookie.
    refresh_token = create_refresh_token(generate_uuid7(), secret_key=_SECRET_KEY)

    decoded = decode_token(refresh_token, secret_key=_SECRET_KEY, expected_type=TokenType.ACCESS)

    assert decoded is None


def test_decode_rejects_expired_token() -> None:
    user_id = generate_uuid7()
    now = datetime.now(UTC)
    expired_payload = {
        "sub": str(user_id),
        "type": TokenType.ACCESS.value,
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
    }
    expired_token = jwt.encode(expired_payload, _SECRET_KEY, algorithm="HS256")

    decoded = decode_token(expired_token, secret_key=_SECRET_KEY, expected_type=TokenType.ACCESS)

    assert decoded is None


def test_decode_rejects_malformed_token() -> None:
    decoded = decode_token("not-a-jwt", secret_key=_SECRET_KEY, expected_type=TokenType.ACCESS)

    assert decoded is None


@pytest.mark.parametrize("token_type", [TokenType.ACCESS, TokenType.REFRESH])
def test_decode_rejects_missing_sub(token_type: TokenType) -> None:
    payload = {"type": token_type.value, "exp": datetime.now(UTC) + timedelta(minutes=5)}
    token = jwt.encode(payload, _SECRET_KEY, algorithm="HS256")

    assert decode_token(token, secret_key=_SECRET_KEY, expected_type=token_type) is None
