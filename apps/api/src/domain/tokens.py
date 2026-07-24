"""JWT access/refresh token issuance + verification — pure functions (SoT B4.6).

Kept in ``domain`` rather than ``services`` because these functions have no
I/O: given a ``secret_key`` (passed in, never imported from ``src.config`` —
see that module's docstring on why domain stays leaf-only) and a user id,
they deterministically produce or consume a signed token. ``decode_token``
follows the same convention as ``domain.security.verify_password``: it
swallows the library's exceptions and reports failure as a plain ``None``
rather than letting callers branch on a menagerie of ``jwt.*Error`` types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import jwt

_ALGORITHM = "HS256"

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


def _encode(*, user_id: UUID, secret_key: str, token_type: TokenType, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type.value,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, secret_key, algorithm=_ALGORITHM)


def create_access_token(user_id: UUID, *, secret_key: str) -> str:
    return _encode(
        user_id=user_id, secret_key=secret_key, token_type=TokenType.ACCESS, ttl=ACCESS_TOKEN_TTL
    )


def create_refresh_token(user_id: UUID, *, secret_key: str) -> str:
    return _encode(
        user_id=user_id, secret_key=secret_key, token_type=TokenType.REFRESH, ttl=REFRESH_TOKEN_TTL
    )


def create_token_pair(user_id: UUID, *, secret_key: str) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id, secret_key=secret_key),
        refresh_token=create_refresh_token(user_id, secret_key=secret_key),
    )


def decode_token(token: str, *, secret_key: str, expected_type: TokenType) -> UUID | None:
    """Verify signature/expiry/type and return the subject's user id, or ``None``.

    Covers: malformed tokens, signature mismatch (wrong/rotated secret_key),
    expiry, and type confusion (e.g. presenting a refresh token where an
    access token is expected) — all collapse to ``None`` so callers (e.g.
    ``api/deps.get_current_user``) have one failure branch, not several.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None

    if payload.get("type") != expected_type.value:
        return None

    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None
