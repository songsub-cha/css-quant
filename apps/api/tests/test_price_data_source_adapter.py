import asyncio
from datetime import date

from src.adapters.data_sources import FakePriceDataSource
from src.domain.market_price import DailyPriceInfo

_TRADE_DATE = date(2026, 7, 29)


def test_fake_price_data_source_returns_expected_tickers() -> None:
    source = FakePriceDataSource()

    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert len(bars) == 4
    assert all(isinstance(b, DailyPriceInfo) for b in bars)
    assert {b.ticker for b in bars} == {"005930", "000660", "086520", "069500"}
    assert all(b.date == _TRADE_DATE for b in bars)


def test_fake_price_data_source_is_deterministic() -> None:
    source = FakePriceDataSource()

    first = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))
    second = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert first == second
