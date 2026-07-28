"""``sync_prices`` (SoT A6.1(2)/C1/C3, services layer).

No DB container in this environment: exercised against
``conftest.FakeAssetRepository``/``FakeMarketPriceRepository``, the same
isolation approach ``test_asset_sync.py`` uses. Uses ``asyncio.run`` directly
(no pytest-asyncio dependency in this project) — same pattern as
``test_asset_sync.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from src.domain.asset import AssetType, Exchange, Market
from src.domain.market_price import DailyPriceInfo
from src.services.price_sync import sync_prices

from .conftest import FakeAssetRepository, FakeMarketPriceRepository


class _StubPriceDataSource:
    def __init__(self, bars: list[DailyPriceInfo]) -> None:
        self._bars = bars

    async def get_daily_ohlcv(self, trade_date: date) -> list[DailyPriceInfo]:
        return self._bars


def _bar(ticker: str, trade_date: date, close: int = 71_200) -> DailyPriceInfo:
    return DailyPriceInfo(
        ticker=ticker,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        adjusted_close=Decimal(close),
        volume=1_000,
        trading_value=Decimal(close * 1_000),
    )


def test_sync_prices_upserts_bar_for_synced_ticker() -> None:
    asset_repo = FakeAssetRepository()
    price_repo = FakeMarketPriceRepository()
    trade_date = date(2026, 7, 29)
    asyncio.run(
        asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
    )
    asset = asyncio.run(asset_repo.get_active_by_ticker("005930", Market.KR))
    assert asset is not None
    source = _StubPriceDataSource([_bar("005930", trade_date)])

    result = asyncio.run(sync_prices(source, asset_repo, price_repo, trade_date))

    assert result.synced == 1
    assert result.skipped_tickers == ()
    assert len(price_repo.prices) == 1
    assert price_repo.prices[0].asset_id == asset.id
    assert price_repo.prices[0].date == trade_date


def test_sync_prices_skips_ticker_not_yet_synced_to_assets() -> None:
    asset_repo = FakeAssetRepository()
    price_repo = FakeMarketPriceRepository()
    trade_date = date(2026, 7, 29)
    source = _StubPriceDataSource([_bar("999999", trade_date)])

    result = asyncio.run(sync_prices(source, asset_repo, price_repo, trade_date))

    assert result.synced == 0
    assert result.skipped_tickers == ("999999",)
    assert price_repo.prices == []


def test_sync_prices_rerun_for_same_asset_and_date_updates_row_in_place() -> None:
    asset_repo = FakeAssetRepository()
    price_repo = FakeMarketPriceRepository()
    trade_date = date(2026, 7, 29)
    asyncio.run(
        asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
    )
    source_first = _StubPriceDataSource([_bar("005930", trade_date, close=71_200)])
    asyncio.run(sync_prices(source_first, asset_repo, price_repo, trade_date))

    source_second = _StubPriceDataSource([_bar("005930", trade_date, close=72_000)])
    result = asyncio.run(sync_prices(source_second, asset_repo, price_repo, trade_date))

    assert result.synced == 1
    assert len(price_repo.prices) == 1
    assert price_repo.prices[0].close == Decimal(72_000)


def test_sync_prices_mixed_batch_syncs_known_and_skips_unknown() -> None:
    asset_repo = FakeAssetRepository()
    price_repo = FakeMarketPriceRepository()
    trade_date = date(2026, 7, 29)
    asyncio.run(
        asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
    )
    source = _StubPriceDataSource([_bar("005930", trade_date), _bar("000660", trade_date)])

    result = asyncio.run(sync_prices(source, asset_repo, price_repo, trade_date))

    assert result.synced == 1
    assert result.skipped_tickers == ("000660",)
    assert len(price_repo.prices) == 1
