"""Fake-by-default ticker master + daily OHLCV data sources (SoT C1 — adapters).

SoT ADR 0004 (fake-by-default adapters) / B3: every external integration
sits behind a Protocol with a deterministic fake as the default
implementation, so the whole app runs with zero API keys/network access.
The real providers (``PykrxDataSource``/``PykrxPriceDataSource``, with a
KRX 정보데이터시스템 fallback for tickers and a FinanceDataReader fallback for
prices) are added in later issues behind these same interfaces. Both fakes
live here rather than in separate files — C1 treats ticker master and daily
OHLCV as the same pykrx-first feed, and there is no one-class-per-file rule
in this codebase.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.asset import Exchange, TickerInfo
from src.domain.market_price import DailyPriceInfo

_FAKE_TICKERS: tuple[TickerInfo, ...] = (
    TickerInfo(ticker="005930", name="삼성전자", exchange=Exchange.KOSPI),
    TickerInfo(ticker="000660", name="SK하이닉스", exchange=Exchange.KOSPI),
    TickerInfo(ticker="086520", name="에코프로", exchange=Exchange.KOSDAQ),
)

# (ticker, open, high, low, close, volume) — plausible KRW won-denominated
# whole-number OHLCV for the same three tickers as ``_FAKE_TICKERS``.
_FAKE_OHLCV: tuple[tuple[str, int, int, int, int, int], ...] = (
    ("005930", 71_000, 71_500, 70_500, 71_200, 15_000_000),
    ("000660", 131_000, 133_000, 130_500, 132_500, 5_000_000),
    ("086520", 245_000, 248_000, 243_000, 246_000, 800_000),
)


class FakeDataSource:
    """Deterministic stand-in for a real ticker-master provider.

    Never calls out to the network. Always returns the same fixed sample of
    tickers, which keeps tests and local runs reproducible without secrets.
    """

    async def list_tickers(self) -> list[TickerInfo]:
        return list(_FAKE_TICKERS)


class FakePriceDataSource:
    """Deterministic stand-in for a real daily OHLCV provider.

    Never calls out to the network. Always returns the same fixed OHLCV
    sample for ``_FAKE_TICKERS``, stamped with the requested ``trade_date``.
    """

    async def get_daily_ohlcv(self, trade_date: date) -> list[DailyPriceInfo]:
        return [
            DailyPriceInfo(
                ticker=ticker,
                date=trade_date,
                open=Decimal(open_),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                adjusted_close=Decimal(close),
                volume=volume,
                trading_value=Decimal(close * volume),
                market_cap=None,
                halted=False,
            )
            for ticker, open_, high, low, close, volume in _FAKE_OHLCV
        ]
