"""SQLAlchemy implementation of the password-reset token repository port (SoT B2 — adapters).

Implements ``src.domain.password_reset.PasswordResetTokenRepository``
structurally, importing only ``domain`` per the layer contract
("adapters는 domain만 import") — same structure as ``SqlAlchemyUserRepository``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.password_reset import PasswordResetToken


class SqlAlchemyPasswordResetTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, user_id: UUID, token_hash: str, expires_at: datetime
    ) -> PasswordResetToken:
        token = PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self._session.add(token)
        await self._session.commit()
        await self._session.refresh(token)
        return token

    async def use_token(self, token_hash: str, *, now: datetime) -> UUID | None:
        # A single UPDATE ... RETURNING makes the lookup and the one-time-use
        # marking atomic: the WHERE clause's `used_at IS NULL` guarantees that
        # if two concurrent confirms race on the same token, only one UPDATE
        # matches a row, so only one call gets a non-empty RETURNING result.
        result = await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(PasswordResetToken.user_id)
        )
        await self._session.commit()
        row = result.first()
        return row[0] if row is not None else None
