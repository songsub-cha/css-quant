"""Worker-level orchestration tests for ``detect_market_regime`` (SoT A6.2/A6.3).

Exercises ``src.workers.market_regime_detection.detect_market_regime``
against ``tests/conftest.py``'s in-memory fakes — no live DB, same shape as
``test_backfill_cli.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.index_price import IndexCode, IndexPriceInfo
from src.domain.market_regime import InsufficientPriceHistoryError, RegimeStatus
from src.workers.market_regime_detection import detect_market_regime

from .conftest import FakeIndexPriceRepository, FakeMarketRegimeRepository


def _bar(index_code: IndexCode, trade_date: date, close: int) -> IndexPriceInfo:
    return IndexPriceInfo(
        index_code=index_code,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1,
        trading_value=Decimal(close),
    )


async def _seed_kospi_history(
    repo: FakeIndexPriceRepository, *, start: date, days: int, close: int
) -> date:
    """Seed ``days`` consecutive flat-KOSPI (+ low-VKOSPI) bars, returning the last date."""
    d = start
    for _ in range(days):
        await repo.upsert(bar=_bar(IndexCode.KOSPI, d, close))
        await repo.upsert(bar=_bar(IndexCode.VKOSPI, d, 20))
        d += timedelta(days=1)
    return d - timedelta(days=1)


def test_detect_market_regime_fetches_judges_and_upserts() -> None:
    async def _run() -> None:
        index_repo = FakeIndexPriceRepository()
        regime_repo = FakeMarketRegimeRepository()
        last_history_date = await _seed_kospi_history(
            index_repo, start=date(2020, 1, 1), days=200, close=2_500
        )
        as_of = last_history_date + timedelta(days=1)
        await index_repo.upsert(bar=_bar(IndexCode.KOSPI, as_of, 2_600))
        await index_repo.upsert(bar=_bar(IndexCode.VKOSPI, as_of, 20))

        row = await detect_market_regime(index_repo, regime_repo, as_of)

        assert row.regime_date == as_of
        assert row.kospi_close == Decimal(2_600)
        assert row.regime == RegimeStatus.DEFENSIVE  # cold start (no prior market_regimes row)
        assert row.signals["raw_normal"] is True
        assert len(regime_repo.regimes) == 1

    asyncio.run(_run())


def test_detect_market_regime_is_idempotent_on_rerun() -> None:
    async def _run() -> None:
        index_repo = FakeIndexPriceRepository()
        regime_repo = FakeMarketRegimeRepository()
        last_history_date = await _seed_kospi_history(
            index_repo, start=date(2020, 1, 1), days=200, close=2_500
        )
        as_of = last_history_date + timedelta(days=1)
        await index_repo.upsert(bar=_bar(IndexCode.KOSPI, as_of, 2_600))
        await index_repo.upsert(bar=_bar(IndexCode.VKOSPI, as_of, 20))

        first = await detect_market_regime(index_repo, regime_repo, as_of)
        second = await detect_market_regime(index_repo, regime_repo, as_of)

        assert first.regime == second.regime
        assert first.kospi_close == second.kospi_close
        assert len(regime_repo.regimes) == 1  # updated in place, not duplicated

    asyncio.run(_run())


def test_detect_market_regime_raises_on_insufficient_kospi_history() -> None:
    async def _run() -> None:
        index_repo = FakeIndexPriceRepository()
        regime_repo = FakeMarketRegimeRepository()
        last_history_date = await _seed_kospi_history(
            index_repo, start=date(2020, 1, 1), days=50, close=2_500
        )
        as_of = last_history_date + timedelta(days=1)
        await index_repo.upsert(bar=_bar(IndexCode.KOSPI, as_of, 2_600))

        with pytest.raises(InsufficientPriceHistoryError):
            await detect_market_regime(index_repo, regime_repo, as_of)

    asyncio.run(_run())


def test_multi_day_hysteresis_round_trip_flips_to_normal_on_3rd_consecutive_day() -> None:
    """DEFENSIVE -> NORMAL only on the 3rd consecutive raw-satisfied trading day.

    KOSPI stays flat/above its MA200 throughout (so it never drives
    ``raw_normal`` on its own) — only VKOSPI (<25 vs >=25) toggles the raw
    NORMAL-condition day to day, isolating the hysteresis state machine at
    the orchestration level (SoT A6.2).
    """

    async def _run() -> None:
        index_repo = FakeIndexPriceRepository()
        regime_repo = FakeMarketRegimeRepository()
        last_history_date = await _seed_kospi_history(
            index_repo, start=date(2020, 1, 1), days=200, close=2_500
        )

        # day1..day5 raw NORMAL-condition per VKOSPI: True, False, True, True, True
        vkospi_by_day = [18, 30, 18, 18, 18]
        expected_regimes = [
            RegimeStatus.DEFENSIVE,  # day1: cold start
            RegimeStatus.DEFENSIVE,  # day2: raw violated (vkospi >= 25)
            RegimeStatus.DEFENSIVE,  # day3: raw satisfied, but day2 breaks the streak
            RegimeStatus.DEFENSIVE,  # day4: only 2 consecutive (day3, day4) so far
            RegimeStatus.NORMAL,  # day5: day3, day4, day5 all satisfied -> flips
        ]

        d = last_history_date
        results = []
        for vkospi in vkospi_by_day:
            d += timedelta(days=1)
            await index_repo.upsert(bar=_bar(IndexCode.KOSPI, d, 2_600))
            await index_repo.upsert(bar=_bar(IndexCode.VKOSPI, d, vkospi))
            results.append(await detect_market_regime(index_repo, regime_repo, d))

        assert [r.regime for r in results] == expected_regimes
        assert [r.signals["raw_normal"] for r in results] == [True, False, True, True, True]

    asyncio.run(_run())
