"""Password reset token model + repository port (SoT B2 — domain, A5.1).

``PasswordResetTokenRepository`` lives here for the same reason
``UserRepository`` (src/domain/user.py) does: ``src.api.v1`` needs the port
type for a ``Depends(...)`` annotation on the confirm/request routes, but
the import-linter contract forbids ``src.api.v1`` from importing
``src.adapters`` directly.

Tokens are never persisted in plaintext — only ``hash_reset_token``'s sha256
digest is stored. sha256 (not argon2id, unlike ``domain.security``) is
enough here because the input is a 256-bit ``secrets.token_urlsafe`` value,
not a human-chosen password: there is no low-entropy search space to slow
down with a deliberately expensive hash.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base
from src.domain.ids import generate_uuid7

# secrets.token_urlsafe(32) -> 256 bits of entropy, base64url-encoded.
_RESET_TOKEN_NBYTES = 32


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=generate_uuid7)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordResetTokenRepository(Protocol):
    """Port ``src.services.password_reset`` depends on."""

    async def create(
        self, *, user_id: UUID, token_hash: str, expires_at: datetime
    ) -> PasswordResetToken: ...

    async def use_token(self, token_hash: str, *, now: datetime) -> UUID | None:
        """Atomically consume an unused, unexpired token; return its owner or ``None``.

        Combines the lookup and the one-time-use marking into a single
        operation so two concurrent confirms for the same token cannot both
        succeed (TOCTOU).
        """
        ...


def generate_reset_token() -> str:
    return secrets.token_urlsafe(_RESET_TOKEN_NBYTES)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
