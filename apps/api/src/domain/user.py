"""User model + external read schema + repository port (SoT B2 — domain).

``UserRepository`` is the port the services layer depends on. It lives here
— rather than alongside its concrete implementation in
``src/adapters/user_repository.py`` — because ``src/api/v1`` needs the type
for a ``Depends(...)`` annotation (mypy strict requires every parameter
typed) but the import-linter contract forbids ``src.api.v1`` from importing
``src.adapters`` directly. Every layer is already allowed to import
``domain``, so defining the port here (Dependency Inversion: the inner layer
declares the contract, the outer adapter satisfies it structurally — Python
``Protocol``s need no explicit inheritance) avoids that conflict without any
``ignore_imports`` exception.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base
from src.domain.ids import format_prefixed_id, generate_uuid7

USER_ID_PREFIX = "usr"


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=generate_uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserRead(BaseModel):
    """External-facing representation — ``password_hash`` deliberately absent."""

    model_config = ConfigDict(frozen=True)

    id: str
    email: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserRead:
        return cls(
            id=format_prefixed_id(USER_ID_PREFIX, user.id),
            email=user.email,
            created_at=user.created_at,
        )


class UserRepository(Protocol):
    """Port ``src.services.auth`` depends on; ``SqlAlchemyUserRepository`` implements it."""

    async def exists_any(self) -> bool: ...

    async def create(self, *, email: str, password_hash: str) -> User: ...
