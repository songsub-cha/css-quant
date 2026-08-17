"""Integration test for ``SqlAlchemyWatchlistItemRepository`` (SoT A5.2/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — same rationale as
``test_ai_score_repository.py``. ``watchlist_items`` has FKs to both
``users.id`` and ``assets.id`` and a ``UNIQUE(user_id, asset_id)``
constraint, so every test here seeds real ``users``/``assets`` rows first.

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``postgres_url`` fixture below skips the whole module when
Docker can't be reached. Only Docker-equipped CI actually exercises the
assertions here.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.db import get_engine
from src.adapters.user_repository import SqlAlchemyUserRepository
from src.adapters.watchlist_repository import SqlAlchemyWatchlistItemRepository
from src.domain.asset import AssetType, Exchange, Market
from src.domain.watchlist import WatchlistItem, WatchlistItemInfo, WatchlistKind

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping watchlist repository test ({exc})")
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


async def _seed_asset(session: AsyncSession, *, ticker: str = "005930") -> UUID:
    asset = await SqlAlchemyAssetRepository(session).upsert_active(
        ticker=ticker,
        name="삼성전자",
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )
    return asset.id


def test_upsert_inserts_new_watchlist_item(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="upsert-insert@example.com")
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyWatchlistItemRepository(session)

            row = await repo.upsert(
                item=WatchlistItemInfo(
                    user_id=user_id, asset_id=asset_id, kind=WatchlistKind.WATCH, note="관심"
                )
            )

            assert row.user_id == user_id
            assert row.asset_id == asset_id
            assert row.kind == WatchlistKind.WATCH
            assert row.note == "관심"

            result = await session.execute(
                sa.select(WatchlistItem).where(
                    WatchlistItem.user_id == user_id, WatchlistItem.asset_id == asset_id
                )
            )
            assert result.scalar_one().kind == WatchlistKind.WATCH

    asyncio.run(_run())


def test_upsert_updates_existing_row_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="upsert-update@example.com")
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyWatchlistItemRepository(session)

            first = await repo.upsert(
                item=WatchlistItemInfo(user_id=user_id, asset_id=asset_id, kind=WatchlistKind.WATCH)
            )
            second = await repo.upsert(
                item=WatchlistItemInfo(
                    user_id=user_id, asset_id=asset_id, kind=WatchlistKind.EXCLUDE, note="제외"
                )
            )

            assert first.id == second.id
            assert second.kind == WatchlistKind.EXCLUDE
            assert second.note == "제외"

            result = await session.execute(
                sa.select(WatchlistItem).where(
                    WatchlistItem.user_id == user_id, WatchlistItem.asset_id == asset_id
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].kind == WatchlistKind.EXCLUDE

    asyncio.run(_run())


def test_upsert_with_nonexistent_asset_id_raises_integrity_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="upsert-bad-asset@example.com")
            repo = SqlAlchemyWatchlistItemRepository(session)
            with pytest.raises(IntegrityError):
                await repo.upsert(
                    item=WatchlistItemInfo(
                        user_id=user_id, asset_id=uuid4(), kind=WatchlistKind.WATCH
                    )
                )

    asyncio.run(_run())


def test_remove_deletes_existing_row(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="remove-existing@example.com")
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyWatchlistItemRepository(session)
            await repo.upsert(
                item=WatchlistItemInfo(user_id=user_id, asset_id=asset_id, kind=WatchlistKind.WATCH)
            )

            await repo.remove(user_id=user_id, asset_id=asset_id)

            result = await session.execute(
                sa.select(WatchlistItem).where(
                    WatchlistItem.user_id == user_id, WatchlistItem.asset_id == asset_id
                )
            )
            assert result.scalar_one_or_none() is None

    asyncio.run(_run())


def test_remove_nonexistent_row_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyWatchlistItemRepository(session)
            await repo.remove(user_id=uuid4(), asset_id=uuid4())

    asyncio.run(_run())


def test_list_by_user_filters_by_kind(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            user_id = await _seed_user(session, email="list-by-kind@example.com")
            watched = await _seed_asset(session, ticker="000001")
            excluded = await _seed_asset(session, ticker="000002")
            repo = SqlAlchemyWatchlistItemRepository(session)
            await repo.upsert(
                item=WatchlistItemInfo(
                    user_id=user_id, asset_id=watched, kind=WatchlistKind.WATCH
                )
            )
            await repo.upsert(
                item=WatchlistItemInfo(
                    user_id=user_id, asset_id=excluded, kind=WatchlistKind.EXCLUDE
                )
            )

            all_items = await repo.list_by_user(user_id=user_id)
            excluded_only = await repo.list_by_user(user_id=user_id, kind=WatchlistKind.EXCLUDE)

            assert {i.asset_id for i in all_items} == {watched, excluded}
            assert [i.asset_id for i in excluded_only] == [excluded]

    asyncio.run(_run())


def test_list_by_user_does_not_leak_other_users_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            owner = await _seed_user(session, email="list-owner@example.com")
            other = await _seed_user(session, email="list-other@example.com")
            asset_id = await _seed_asset(session, ticker="000003")
            repo = SqlAlchemyWatchlistItemRepository(session)
            await repo.upsert(
                item=WatchlistItemInfo(user_id=other, asset_id=asset_id, kind=WatchlistKind.WATCH)
            )

            items = await repo.list_by_user(user_id=owner)

            assert items == []

    asyncio.run(_run())
