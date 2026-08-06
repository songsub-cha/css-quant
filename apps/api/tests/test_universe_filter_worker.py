"""Worker-level orchestration tests for ``evaluate_universe`` (SoT A6.1).

Exercises ``src.workers.universe_filter.evaluate_universe`` against
``tests/conftest.py``'s in-memory fakes — no live DB, same shape as
``test_market_regime_detection.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from src.domain.asset import AssetType, Exchange, Market
from src.domain.market_price import DailyPriceInfo
from src.domain.universe_filter import UniverseExclusionReason, UniverseThresholds
from src.workers.universe_filter import evaluate_universe

from .conftest import FakeAssetRepository, FakeMarketPriceRepository

_AS_OF = date(2026, 8, 7)
_THRESHOLDS = UniverseThresholds(
    market_cap_min=Decimal("300000000000"),
    avg_trading_value_min=Decimal("1000000000"),
    min_listed_days=60,
)


def _bar(
    ticker: str, trade_date: date, *, trading_value: int, market_cap: int | None
) -> DailyPriceInfo:
    return DailyPriceInfo(
        ticker=ticker,
        date=trade_date,
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        adjusted_close=Decimal(1),
        volume=1,
        trading_value=Decimal(trading_value),
        market_cap=Decimal(market_cap) if market_cap is not None else None,
    )


async def _seed_20_trading_days(
    price_repo: FakeMarketPriceRepository,
    asset_id: UUID,
    ticker: str,
    *,
    end: date,
    trading_value: int,
    market_cap: int | None,
) -> None:
    d = end - timedelta(days=19)
    while d <= end:
        await price_repo.upsert(
            asset_id=asset_id,
            bar=_bar(ticker, d, trading_value=trading_value, market_cap=market_cap),
        )
        d += timedelta(days=1)


def test_evaluate_universe_includes_qualifying_stock() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()

        asset = await asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        await _seed_20_trading_days(
            price_repo,
            asset.id,
            "005930",
            end=_AS_OF,
            trading_value=2_000_000_000,
            market_cap=400_000_000_000,
        )

        results = await evaluate_universe(
            asset_repo, price_repo, as_of_date=_AS_OF, thresholds=_THRESHOLDS
        )

        assert len(results) == 1
        assert results[0].asset_id == asset.id
        assert results[0].included is True

    asyncio.run(_run())


def test_evaluate_universe_excludes_etf() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()

        etf = await asset_repo.upsert_active(
            ticker="069500",
            name="KODEX 200",
            market=Market.KR,
            asset_type=AssetType.ETF,
            exchange=Exchange.KOSPI,
        )
        await _seed_20_trading_days(
            price_repo,
            etf.id,
            "069500",
            end=_AS_OF,
            trading_value=2_000_000_000,
            market_cap=400_000_000_000,
        )

        results = await evaluate_universe(
            asset_repo, price_repo, as_of_date=_AS_OF, thresholds=_THRESHOLDS
        )

        assert results == []

    asyncio.run(_run())


def test_evaluate_universe_excludes_inactive_asset() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()

        asset = await asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        asset.is_active = False

        results = await evaluate_universe(
            asset_repo, price_repo, as_of_date=_AS_OF, thresholds=_THRESHOLDS
        )

        assert results == []

    asyncio.run(_run())


def test_evaluate_universe_excludes_stock_with_no_price_data_that_day() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()

        asset = await asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        # No market_prices rows seeded at all -> both market_cap and
        # avg_trading_value_20d are missing.

        (result,) = await evaluate_universe(
            asset_repo, price_repo, as_of_date=_AS_OF, thresholds=_THRESHOLDS
        )

        assert result.asset_id == asset.id
        assert result.included is False
        assert set(result.exclusion_reasons) == {
            UniverseExclusionReason.MARKET_CAP_DATA_MISSING,
            UniverseExclusionReason.AVG_TRADING_VALUE_DATA_MISSING,
        }

    asyncio.run(_run())


def test_evaluate_universe_avg_trading_value_ignores_future_dates() -> None:
    """Look-ahead guard at the worker level: a market_prices row dated after
    as_of_date must never enter the 20-day average (SoT A2 원칙 8)."""

    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()

        asset = await asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        # 20 trailing days all below the trading-value floor...
        await _seed_20_trading_days(
            price_repo,
            asset.id,
            "005930",
            end=_AS_OF,
            trading_value=500_000_000,
            market_cap=400_000_000_000,
        )
        # ...but a future day far above it, which must not leak into the average.
        await price_repo.upsert(
            asset_id=asset.id,
            bar=_bar(
                "005930",
                _AS_OF + timedelta(days=1),
                trading_value=100_000_000_000,
                market_cap=400_000_000_000,
            ),
        )

        (result,) = await evaluate_universe(
            asset_repo, price_repo, as_of_date=_AS_OF, thresholds=_THRESHOLDS
        )

        assert result.included is False
        assert UniverseExclusionReason.AVG_TRADING_VALUE_BELOW_MIN in result.exclusion_reasons

    asyncio.run(_run())
