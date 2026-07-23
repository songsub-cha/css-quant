"""SQLAlchemy implementation of the user repository port (SoT B2 — adapters).

Implements ``src.domain.user.UserRepository`` structurally — Python
``Protocol``s use structural typing, so no explicit inheritance is needed
and this module keeps importing only ``domain``, per the layer contract
("adapters는 domain만 import").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.user import User


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists_any(self) -> bool:
        result = await self._session.execute(select(User.id).limit(1))
        return result.first() is not None

    async def create(self, *, email: str, password_hash: str) -> User:
        user = User(email=email, password_hash=password_hash)
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        await self._session.refresh(user)
        return user
