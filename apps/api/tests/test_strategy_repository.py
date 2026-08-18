"""Integration test for ``SqlAlchemyStrategyRepository`` (SoT A5.3/C3).

Same structure as ``test_watchlist_repository.py``: spins up a real
Postgres container via ``testcontainers`` and runs the actual Alembic
migration chain against it.

Docker is unavailable in this environment and in the css-executor worktree,
so the module-scoped ``postgres_url`` fixture below skips the whole module
when Docker can't be reached. Only Docker-equipped CI actually exercises
the assertions here.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.db import get_engine
from src.adapters.strategy_repository import SqlAlchemyStrategyRepository
from src.adapters.user_repository import SqlAlchemyUserRepository
from src.domain.strategy import ExecutionMode, Strategy, StrategyInfo, StrategyStatus

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping strategy repository test ({exc})")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def _run_alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_API_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
    )


@pytest.fixture(scope="module")
def migrated_database_url(postgres_url: str) -> str:
    _run_alembic(postgres_url, "upgrade", "head")
    return postgres_url


@pytest.fixture(scope="module")
def engine(migrated_database_url: str) -> Generator[AsyncEngine, None, None]:
    eng = get_engine(migrated_database_url)
    try:
        yield eng
    finally:
        asyncio.run(eng.dispose())


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_user(session: AsyncSession, *, email: str) -> UUID:
    user = await SqlAlchemyUserRepository(session).create(email=email, password_hash="hashed")
    return user.id


def _strategy_info(user_id: UUID, *, name: str = "추세추종 전략") -> StrategyInfo:
    return StrategyInfo(
        user_id=user_id,
        name=name,
        description="테스트 전략",
        execution_mode=ExecutionMode.BACKTEST,
        config={"ai_filter": {"min_score": "70"}},
    )


def test_create_inserts_draft_version_1_strategy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="strategy-create@example.com")
            repo = SqlAlchemyStrategyRepository(session)

            row = await repo.create(info=_strategy_info(user_id))

            assert row.user_id == user_id
            assert row.status == StrategyStatus.DRAFT
            assert row.version == 1
            assert row.config == {"ai_filter": {"min_score": "70"}}

    asyncio.run(_run())


def test_get_by_id_returns_none_for_other_user(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            owner = await _seed_user(session, email="strategy-owner@example.com")
            other = await _seed_user(session, email="strategy-other@example.com")
            repo = SqlAlchemyStrategyRepository(session)
            created = await repo.create(info=_strategy_info(owner))

            result = await repo.get_by_id(user_id=other, strategy_id=created.id)

            assert result is None

    asyncio.run(_run())


def test_get_by_id_returns_none_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="strategy-unknown@example.com")
            repo = SqlAlchemyStrategyRepository(session)

            result = await repo.get_by_id(user_id=user_id, strategy_id=uuid4())

            assert result is None

    asyncio.run(_run())


def test_get_by_id_excludes_soft_deleted_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="strategy-deleted@example.com")
            repo = SqlAlchemyStrategyRepository(session)
            created = await repo.create(info=_strategy_info(user_id))
            await repo.soft_delete(created)

            result = await repo.get_by_id(user_id=user_id, strategy_id=created.id)

            assert result is None

    asyncio.run(_run())


def test_list_by_user_filters_by_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="strategy-list@example.com")
            repo = SqlAlchemyStrategyRepository(session)
            draft = await repo.create(info=_strategy_info(user_id, name="드래프트"))
            active = await repo.create(info=_strategy_info(user_id, name="활성"))
            active.status = StrategyStatus.ACTIVE
            await repo.update(active)

            all_strategies = await repo.list_by_user(user_id=user_id)
            active_only = await repo.list_by_user(user_id=user_id, status=StrategyStatus.ACTIVE)

            assert {s.id for s in all_strategies} == {draft.id, active.id}
            assert [s.id for s in active_only] == [active.id]

    asyncio.run(_run())


def test_list_by_user_excludes_other_users_and_soft_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            owner = await _seed_user(session, email="strategy-list-owner@example.com")
            other = await _seed_user(session, email="strategy-list-other@example.com")
            repo = SqlAlchemyStrategyRepository(session)
            await repo.create(info=_strategy_info(other, name="다른 사용자 전략"))
            deleted = await repo.create(info=_strategy_info(owner, name="삭제될 전략"))
            await repo.soft_delete(deleted)

            result = await repo.list_by_user(user_id=owner)

            assert result == []

    asyncio.run(_run())


def test_update_persists_mutated_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="strategy-update@example.com")
            repo = SqlAlchemyStrategyRepository(session)
            created = await repo.create(info=_strategy_info(user_id))

            created.name = "수정된 이름"
            created.version = 2
            updated = await repo.update(created)

            assert updated.name == "수정된 이름"
            assert updated.version == 2

            result = await session.execute(
                sa.select(Strategy).where(Strategy.id == created.id)
            )
            assert result.scalar_one().name == "수정된 이름"

    asyncio.run(_run())


def test_soft_delete_sets_deleted_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="strategy-soft-delete@example.com")
            repo = SqlAlchemyStrategyRepository(session)
            created = await repo.create(info=_strategy_info(user_id))
            assert created.deleted_at is None

            await repo.soft_delete(created)

            result = await session.execute(
                sa.select(Strategy).where(Strategy.id == created.id)
            )
            assert result.scalar_one().deleted_at is not None

    asyncio.run(_run())
