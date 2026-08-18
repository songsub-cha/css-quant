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

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.adapters.ai_score_repository import SqlAlchemyAssetScoreRepository
from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.db import get_engine
from src.adapters.email import FakeEmailSender
from src.adapters.glossary import GLOSSARY_PATH, load_glossary_terms
from src.adapters.job_run_repository import SqlAlchemyJobRunRepository
from src.adapters.password_reset_repository import SqlAlchemyPasswordResetTokenRepository
from src.adapters.strategy_repository import SqlAlchemyStrategyRepository
from src.adapters.user_repository import SqlAlchemyUserRepository
from src.adapters.watchlist_repository import SqlAlchemyWatchlistItemRepository
from src.api.cookies import ACCESS_TOKEN_COOKIE
from src.config import Settings
from src.domain.ai_score import AssetScoreRepository
from src.domain.asset import AssetRepository
from src.domain.email import EmailSender
from src.domain.glossary import GlossaryTerm
from src.domain.job_run import JobRunRepository
from src.domain.password_reset import PasswordResetTokenRepository
from src.domain.strategy import StrategyRepository
from src.domain.tokens import TokenType, decode_token
from src.domain.user import User, UserRepository
from src.domain.watchlist import WatchlistItemRepository
from src.errors import ApiError, ErrorCode


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


async def get_asset_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AssetRepository:
    # Tests override this with conftest.FakeAssetRepository, the same way
    # get_user_repository is overridden (no DB container in this
    # environment).
    return SqlAlchemyAssetRepository(session)


async def get_asset_score_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AssetScoreRepository:
    # Tests override this with conftest.FakeAssetScoreRepository, the same
    # way get_asset_repository is overridden (no DB container in this
    # environment).
    return SqlAlchemyAssetScoreRepository(session)


async def get_job_run_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobRunRepository:
    # Tests override this with an in-memory fake, the same way
    # get_asset_repository is overridden (no DB container in this
    # environment).
    return SqlAlchemyJobRunRepository(session)


async def get_watchlist_item_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WatchlistItemRepository:
    # Tests override this with conftest.FakeWatchlistItemRepository, the same
    # way get_asset_score_repository is overridden (no DB container in this
    # environment).
    return SqlAlchemyWatchlistItemRepository(session)


async def get_strategy_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StrategyRepository:
    # Tests override this with conftest.FakeStrategyRepository, the same
    # way get_watchlist_item_repository is overridden (no DB container in
    # this environment).
    return SqlAlchemyStrategyRepository(session)


async def get_password_reset_token_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PasswordResetTokenRepository:
    # Tests override this with conftest.FakePasswordResetTokenRepository, the
    # same way get_user_repository is overridden (no DB container here).
    return SqlAlchemyPasswordResetTokenRepository(session)


@lru_cache
def get_glossary_terms() -> list[GlossaryTerm]:
    # Static content (SoT A6.12 — git-versioned, code-reviewed, no DB
    # table): parsed once per process, same singleton pattern as
    # get_settings/get_db_engine above.
    return load_glossary_terms(GLOSSARY_PATH)


@lru_cache
def get_email_sender() -> EmailSender:
    # SoT B3/ADR 0004: fake-by-default. A real SMTP-backed adapter (gated by
    # an ``EMAIL_ADAPTER``-style env var, mirroring ``LLM_ADAPTER``) is a
    # later issue's scope — see src/adapters/email.py.
    return FakeEmailSender()


def get_signup_enabled(settings: Annotated[Settings, Depends(get_settings)]) -> bool:
    return settings.signup_enabled


def get_secret_key(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    return settings.secret_key


def get_cookie_secure(settings: Annotated[Settings, Depends(get_settings)]) -> bool:
    return settings.cookie_secure


async def get_current_user(
    request: Request,
    repo: Annotated[UserRepository, Depends(get_user_repository)],
    secret_key: Annotated[str, Depends(get_secret_key)],
) -> User:
    # Reused by every protected router via Depends(get_current_user) — see
    # api/v1/auth.py's /me for the first consumer. Any failure mode (cookie
    # absent, signature mismatch, expired, or a refresh token presented
    # where an access token is expected) collapses to the same 401 so a
    # caller can't distinguish "no cookie" from "bad cookie" (SoT B4.5 —
    # don't leak more than necessary about why auth failed).
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    user_id = (
        decode_token(token, secret_key=secret_key, expected_type=TokenType.ACCESS)
        if token is not None
        else None
    )
    user = await repo.get_by_id(user_id) if user_id is not None else None
    if user is None:
        raise ApiError(status=401, code=ErrorCode.UNAUTHORIZED, detail="Not authenticated.")
    return user
