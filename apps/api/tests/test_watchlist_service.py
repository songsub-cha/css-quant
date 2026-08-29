"""``src.services.watchlist`` pure unit tests (SoT A5.2 — services layer).

No DB container in this environment: exercised against
``conftest.FakeWatchlistItemRepository``/``FakeAssetRepository``, the same
isolation approach ``test_scores_service.py`` uses. Uses ``asyncio.run``
directly (no pytest-asyncio dependency in this project).
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from src.domain.asset import Asset, AssetType, Exchange, Market
from src.domain.watchlist import WatchlistKind
from src.errors import ApiError
from src.services.watchlist import add_or_update_item, list_items, remove_item

from .conftest import FakeAssetRepository, FakeWatchlistItemRepository


async def _seed_asset(asset_repo: FakeAssetRepository, ticker: str = "005930") -> Asset:
    return await asset_repo.upsert_active(
        ticker=ticker,
        name="삼성전자",
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )


def test_add_or_update_item_with_nonexistent_asset_raises_404() -> None:
    async def _run() -> None:
        watchlist_repo = FakeWatchlistItemRepository()
        asset_repo = FakeAssetRepository()

        with pytest.raises(ApiError) as exc_info:
            await add_or_update_item(
                watchlist_repo,
                asset_repo,
                user_id=uuid4(),
                asset_id=uuid4(),
                kind=WatchlistKind.WATCH,
                note=None,
            )

        assert exc_info.value.status == 404
        assert exc_info.value.code.value == "ASSET_NOT_FOUND"
        assert watchlist_repo.items == []

    asyncio.run(_run())


def test_add_or_update_item_happy_path_inserts_row() -> None:
    async def _run() -> None:
        watchlist_repo = FakeWatchlistItemRepository()
        asset_repo = FakeAssetRepository()
        asset = await _seed_asset(asset_repo)
        user_id = uuid4()

        item = await add_or_update_item(
            watchlist_repo,
            asset_repo,
            user_id=user_id,
            asset_id=asset.id,
            kind=WatchlistKind.WATCH,
            note="관심 종목",
        )

        assert item.user_id == user_id
        assert item.asset_id == asset.id
        assert item.kind == WatchlistKind.WATCH
        assert item.note == "관심 종목"

    asyncio.run(_run())


def test_add_or_update_item_re_add_updates_kind_in_place() -> None:
    async def _run() -> None:
        watchlist_repo = FakeWatchlistItemRepository()
        asset_repo = FakeAssetRepository()
        asset = await _seed_asset(asset_repo)
        user_id = uuid4()

        await add_or_update_item(
            watchlist_repo,
            asset_repo,
            user_id=user_id,
            asset_id=asset.id,
            kind=WatchlistKind.WATCH,
            note=None,
        )
        await add_or_update_item(
            watchlist_repo,
            asset_repo,
            user_id=user_id,
            asset_id=asset.id,
            kind=WatchlistKind.EXCLUDE,
            note="제외로 전환",
        )

        assert len(watchlist_repo.items) == 1
        assert watchlist_repo.items[0].kind == WatchlistKind.EXCLUDE
        assert watchlist_repo.items[0].note == "제외로 전환"

    asyncio.run(_run())


def test_remove_item_delegates_to_repository() -> None:
    async def _run() -> None:
        watchlist_repo = FakeWatchlistItemRepository()
        asset_repo = FakeAssetRepository()
        asset = await _seed_asset(asset_repo)
        user_id = uuid4()
        await add_or_update_item(
            watchlist_repo,
            asset_repo,
            user_id=user_id,
            asset_id=asset.id,
            kind=WatchlistKind.WATCH,
            note=None,
        )

        await remove_item(watchlist_repo, user_id=user_id, asset_id=asset.id)

        assert watchlist_repo.items == []

    asyncio.run(_run())


def test_remove_item_nonexistent_row_does_not_raise() -> None:
    async def _run() -> None:
        watchlist_repo = FakeWatchlistItemRepository()

        await remove_item(watchlist_repo, user_id=uuid4(), asset_id=uuid4())

    asyncio.run(_run())


def test_list_items_filters_by_kind() -> None:
    async def _run() -> None:
        watchlist_repo = FakeWatchlistItemRepository()
        asset_repo = FakeAssetRepository()
        watched = await _seed_asset(asset_repo, ticker="000001")
        excluded = await _seed_asset(asset_repo, ticker="000002")
        user_id = uuid4()
        await add_or_update_item(
            watchlist_repo,
            asset_repo,
            user_id=user_id,
            asset_id=watched.id,
            kind=WatchlistKind.WATCH,
            note=None,
        )
        await add_or_update_item(
            watchlist_repo,
            asset_repo,
            user_id=user_id,
            asset_id=excluded.id,
            kind=WatchlistKind.EXCLUDE,
            note=None,
        )

        all_pairs = await list_items(watchlist_repo, asset_repo, user_id=user_id, kind=None)
        excluded_only = await list_items(
            watchlist_repo, asset_repo, user_id=user_id, kind=WatchlistKind.EXCLUDE
        )

        assert {item.asset_id for item, _asset in all_pairs} == {watched.id, excluded.id}
        assert [item.asset_id for item, _asset in excluded_only] == [excluded.id]
        assert {asset.ticker for _item, asset in all_pairs} == {"000001", "000002"}

    asyncio.run(_run())


def test_list_items_skips_rows_whose_asset_is_missing() -> None:
    async def _run() -> None:
        watchlist_repo = FakeWatchlistItemRepository()
        asset_repo = FakeAssetRepository()
        asset = await _seed_asset(asset_repo)
        user_id = uuid4()
        await add_or_update_item(
            watchlist_repo,
            asset_repo,
            user_id=user_id,
            asset_id=asset.id,
            kind=WatchlistKind.WATCH,
            note=None,
        )
        # Simulate the asset becoming unresolvable after the watchlist row was created.
        asset_repo.assets.clear()

        pairs = await list_items(watchlist_repo, asset_repo, user_id=user_id, kind=None)

        assert pairs == []

    asyncio.run(_run())
