"""``sync_index_prices`` (SoT A6.2/A6.3, services layer).

No DB container in this environment: exercised against
``conftest.FakeIndexPriceRepository``, same isolation approach as
``test_price_sync.py``. Uses ``asyncio.run`` directly (no pytest-asyncio
dependency in this project).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from src.domain.index_price import IndexCode, IndexPriceInfo
from src.services.index_price_sync import sync_index_prices

from .conftest import FakeIndexPriceRepository


class _StubIndexPriceDataSource:
    def __init__(self, bars: list[IndexPriceInfo]) -> None:
        self._bars = bars

    async def get_daily_ohlcv(self, trade_date: date) -> list[IndexPriceInfo]:
        return self._bars


def _bar(index_code: IndexCode, trade_date: date, close: int) -> IndexPriceInfo:
    return IndexPriceInfo(
        index_code=index_code,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1_000,
        trading_value=Decimal(close * 1_000),
    )


def test_sync_index_prices_upserts_both_index_bars() -> None:
    repo = FakeIndexPriceRepository()
    trade_date = date(2026, 7, 29)
    source = _StubIndexPriceDataSource(
        [_bar(IndexCode.KOSPI, trade_date, 2_665), _bar(IndexCode.VKOSPI, trade_date, 18)]
    )

    result = asyncio.run(sync_index_prices(source, repo, trade_date))

    assert result.synced == 2
    assert {p.index_code for p in repo.prices} == {IndexCode.KOSPI, IndexCode.VKOSPI}
    assert all(p.date == trade_date for p in repo.prices)


def test_sync_index_prices_when_vkospi_missing_only_syncs_kospi() -> None:
    """Mirrors the adapter omitting VKOSPI for a day it couldn't be fetched (SoT A6.4)."""
    repo = FakeIndexPriceRepository()
    trade_date = date(2026, 7, 29)
    source = _StubIndexPriceDataSource([_bar(IndexCode.KOSPI, trade_date, 2_665)])

    result = asyncio.run(sync_index_prices(source, repo, trade_date))

    assert result.synced == 1
    assert {p.index_code for p in repo.prices} == {IndexCode.KOSPI}


def test_sync_index_prices_rerun_for_same_date_updates_row_in_place() -> None:
    repo = FakeIndexPriceRepository()
    trade_date = date(2026, 7, 29)
    source_first = _StubIndexPriceDataSource([_bar(IndexCode.KOSPI, trade_date, 2_665)])
    asyncio.run(sync_index_prices(source_first, repo, trade_date))

    source_second = _StubIndexPriceDataSource([_bar(IndexCode.KOSPI, trade_date, 2_700)])
    result = asyncio.run(sync_index_prices(source_second, repo, trade_date))

    assert result.synced == 1
    assert len(repo.prices) == 1
    assert repo.prices[0].close == Decimal(2_700)
