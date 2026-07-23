"""DI composition point (SoT B1/B2 — "DI는 `api/deps.py`").

This is one of the two places allowed to import ``src.config`` directly
(the other is ``alembic/env.py``, which sits outside the layer graph). It is
also where concrete adapters (``SqlAlchemyUserRepository``) get wired to the
domain-layer ports (``UserRepository``) that services depend on —
``src.api.v1`` may not import ``src.adapters`` directly, so routers only
ever see the port type via ``Depends(get_user_repository)`` here. Tests
override these dependencies (e.g. ``get_user_repository``) with in-memory
fakes via ``app.dependency_overrides``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.adapters.db import get_engine
from src.adapters.user_repository import SqlAlchemyUserRepository
from src.config import Settings
from src.domain.user import UserRepository


@lru_cache
def get_settings() -> Settings:
    # cookie_secure (SoT D2) has no Python-level default by design — it's
    # loaded from the environment/.env at runtime by BaseSettings. mypy's
    # dataclass_transform-derived __init__ signature can't see that binding
    # and statically demands the kwarg; the ignore is for that gap only.
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_db_engine() -> AsyncEngine:
    return get_engine(get_settings().database_url)


@lru_cache
def _get_session_maker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_db_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with _get_session_maker()() as session:
        yield session


async def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRepository:
    # Tests override this dependency with an in-memory fake (no DB
    # container in this environment) — see tests/test_auth_bootstrap.py.
    return SqlAlchemyUserRepository(session)


def get_signup_enabled(settings: Annotated[Settings, Depends(get_settings)]) -> bool:
    return settings.signup_enabled
