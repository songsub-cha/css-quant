"""``sync_assets`` (SoT C1/C3, services layer).

No DB container in this environment: exercised against
``conftest.FakeAssetRepository``, the same isolation approach the other
service-level tests use for their repository ports. Uses ``asyncio.run``
directly (no pytest-asyncio dependency in this project) — same pattern as
``test_data_source_adapter.py``.
"""

from __future__ import annotations

import asyncio

from src.domain.asset import AssetType, Exchange, TickerInfo
from src.services.asset_sync import sync_assets

from .conftest import FakeAssetRepository


class _StubDataSource:
    def __init__(self, tickers: list[TickerInfo]) -> None:
        self._tickers = tickers

    async def list_tickers(self) -> list[TickerInfo]:
        return self._tickers


def test_sync_assets_inserts_new_ticker_as_active_stock() -> None:
    repo = FakeAssetRepository()
    source = _StubDataSource(
        [
            TickerInfo(
                ticker="005930",
                name="삼성전자",
                exchange=Exchange.KOSPI,
                asset_type=AssetType.STOCK,
            )
        ]
    )

    count = asyncio.run(sync_assets(source, repo))

    assert count == 1
    assert len(repo.assets) == 1
    asset = repo.assets[0]
    assert asset.ticker == "005930"
    assert asset.name == "삼성전자"
    assert asset.exchange == Exchange.KOSPI
    assert asset.asset_type == AssetType.STOCK
    assert asset.is_active is True


def test_sync_assets_upserts_etf_ticker_as_etf_asset_type() -> None:
    repo = FakeAssetRepository()
    source = _StubDataSource(
        [
            TickerInfo(
                ticker="069500", name="KODEX 200", exchange=Exchange.KOSPI, asset_type=AssetType.ETF
            )
        ]
    )

    count = asyncio.run(sync_assets(source, repo))

    assert count == 1
    assert repo.assets[0].asset_type == AssetType.ETF


def test_sync_assets_updates_existing_active_ticker_in_place() -> None:
    repo = FakeAssetRepository()
    asyncio.run(
        sync_assets(
            _StubDataSource(
                [
                    TickerInfo(
                        ticker="005930",
                        name="Old Name",
                        exchange=Exchange.KOSPI,
                        asset_type=AssetType.STOCK,
                    )
                ]
            ),
            repo,
        )
    )

    asyncio.run(
        sync_assets(
            _StubDataSource(
                [
                    TickerInfo(
                        ticker="005930",
                        name="New Name",
                        exchange=Exchange.KOSDAQ,
                        asset_type=AssetType.STOCK,
                    )
                ]
            ),
            repo,
        )
    )

    assert len(repo.assets) == 1
    assert repo.assets[0].name == "New Name"
    assert repo.assets[0].exchange == Exchange.KOSDAQ


def test_sync_assets_relisting_creates_new_row_and_preserves_inactive_row() -> None:
    repo = FakeAssetRepository()
    ticker = TickerInfo(
        ticker="000660", name="SK하이닉스", exchange=Exchange.KOSPI, asset_type=AssetType.STOCK
    )
    asyncio.run(sync_assets(_StubDataSource([ticker]), repo))

    # Simulate delisting outside sync_assets' scope (SoT C3: detecting a
    # ticker that dropped out of list_tickers() is a later issue).
    repo.assets[0].is_active = False

    asyncio.run(sync_assets(_StubDataSource([ticker]), repo))

    assert len(repo.assets) == 2
    inactive = [a for a in repo.assets if not a.is_active]
    active = [a for a in repo.assets if a.is_active]
    assert len(inactive) == 1
    assert len(active) == 1
    assert inactive[0].ticker == active[0].ticker == "000660"
