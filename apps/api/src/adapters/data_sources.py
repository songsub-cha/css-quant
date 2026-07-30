"""Fake-by-default + pykrx-primary ticker master / daily OHLCV data sources (SoT C1 — adapters).

SoT ADR 0004 (fake-by-default adapters) / B3: every external integration
sits behind a Protocol with a deterministic fake as the default
implementation, so the whole app runs with zero API keys/network access.
``PykrxDataSource``/``PykrxPriceDataSource`` are the real providers, selected
via ``Settings.data_source`` (``DATA_SOURCE=fake|krx``) in
``src/workers/settings.py``. Both fakes (and both real adapters) live here
rather than in separate files — C1 treats ticker master and daily OHLCV as
the same pykrx-first feed, and there is no one-class-per-file rule in this
codebase.

Both real adapters follow SoT C2's collection policy: pykrx is a scraping
library, so every call goes through ``_fetch_with_retry`` (exponential
backoff, up to 3 attempts) and a fixed delay between successive requests;
exhausting retries falls back to the documented secondary source (SoT C1) —
``krx_fallback`` for ticker master, FinanceDataReader for daily OHLCV.
``PykrxPriceDataSource`` fetches the whole market in bulk calls
(``get_market_ohlcv(date, market="ALL")`` for stocks,
``get_etf_ohlcv_by_ticker(date)`` for ETFs) rather than per ticker — the
~2,500-ticker universe (SoT A6.1) would otherwise turn one collection run
into thousands of scraping requests.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import FinanceDataReader as fdr
from pykrx import stock as pykrx_stock

from src.adapters import krx_fallback
from src.domain.asset import AssetType, Exchange, TickerInfo
from src.domain.market_price import DailyPriceInfo

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_INITIAL_BACKOFF_SECONDS = 1.0
_REQUEST_DELAY_SECONDS = 0.2

_STOCK_MARKETS: tuple[tuple[str, Exchange], ...] = (
    ("KOSPI", Exchange.KOSPI),
    ("KOSDAQ", Exchange.KOSDAQ),
)

_FAKE_TICKERS: tuple[TickerInfo, ...] = (
    TickerInfo(
        ticker="005930", name="삼성전자", exchange=Exchange.KOSPI, asset_type=AssetType.STOCK
    ),
    TickerInfo(
        ticker="000660", name="SK하이닉스", exchange=Exchange.KOSPI, asset_type=AssetType.STOCK
    ),
    TickerInfo(
        ticker="086520", name="에코프로", exchange=Exchange.KOSDAQ, asset_type=AssetType.STOCK
    ),
    TickerInfo(
        ticker="069500", name="KODEX 200", exchange=Exchange.KOSPI, asset_type=AssetType.ETF
    ),
)

# (ticker, open, high, low, close, volume) — plausible KRW won-denominated
# whole-number OHLCV for the same four tickers as ``_FAKE_TICKERS``.
_FAKE_OHLCV: tuple[tuple[str, int, int, int, int, int], ...] = (
    ("005930", 71_000, 71_500, 70_500, 71_200, 15_000_000),
    ("000660", 131_000, 133_000, 130_500, 132_500, 5_000_000),
    ("086520", 245_000, 248_000, 243_000, 246_000, 800_000),
    ("069500", 35_000, 35_200, 34_800, 35_100, 2_000_000),
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


async def _fetch_with_retry[T](func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking pykrx/FDR call in a thread, retrying with exponential backoff (SoT C2).

    Broad ``except Exception`` is intentional here: pykrx/FinanceDataReader
    scrape HTML/JSON endpoints not covered by a stable typed exception
    hierarchy, and this is the system boundary SoT 원칙 8 calls out for
    fail-closed retry-then-fallback handling.
    """
    delay = _INITIAL_BACKOFF_SECONDS
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            name = getattr(func, "__name__", repr(func))
            logger.warning("%s failed (attempt %d/%d): %s", name, attempt, _MAX_ATTEMPTS, exc)
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(delay)
                delay *= 2
    assert last_exc is not None
    raise last_exc


class PykrxDataSource:
    """pykrx-primary ticker master provider, KRX 정보데이터시스템 fallback (SoT C1/C2)."""

    async def list_tickers(self) -> list[TickerInfo]:
        try:
            return await self._list_tickers_via_pykrx()
        except Exception:
            logger.warning(
                "pykrx ticker master fetch exhausted retries; falling back to KRX 정보데이터시스템",
                exc_info=True,
            )
            return await asyncio.to_thread(krx_fallback.fetch_ticker_master)

    async def _list_tickers_via_pykrx(self) -> list[TickerInfo]:
        tickers: list[TickerInfo] = []
        for market, exchange in _STOCK_MARKETS:
            codes = await _fetch_with_retry(pykrx_stock.get_market_ticker_list, market=market)
            for code in codes:
                name = await _fetch_with_retry(pykrx_stock.get_market_ticker_name, code)
                tickers.append(
                    TickerInfo(
                        ticker=code, name=name, exchange=exchange, asset_type=AssetType.STOCK
                    )
                )
                await asyncio.sleep(_REQUEST_DELAY_SECONDS)

        etf_codes = await _fetch_with_retry(pykrx_stock.get_etf_ticker_list)
        for code in etf_codes:
            name = await _fetch_with_retry(pykrx_stock.get_etf_ticker_name, code)
            tickers.append(
                TickerInfo(
                    ticker=code, name=name, exchange=Exchange.KOSPI, asset_type=AssetType.ETF
                )
            )
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
        return tickers


def _ohlcv_row_to_bar(ticker: str, row: Any, trade_date: date) -> DailyPriceInfo:
    close = Decimal(str(row["종가"]))
    return DailyPriceInfo(
        ticker=ticker,
        date=trade_date,
        open=Decimal(str(row["시가"])),
        high=Decimal(str(row["고가"])),
        low=Decimal(str(row["저가"])),
        close=close,
        # pykrx's bulk 전종목 endpoint has no adjusted-close column — a fresh
        # bar's adjusted close equals its raw close until a later split/
        # dividend triggers the C2 재적재(reload) path, out of this issue's scope.
        adjusted_close=close,
        volume=int(row["거래량"]),
        trading_value=Decimal(str(row["거래대금"])),
        market_cap=None,
        halted=False,
    )


def _fdr_row_to_bar(ticker: str, row: Any, trade_date: date) -> DailyPriceInfo:
    close = Decimal(str(row["Close"]))
    volume = int(row["Volume"])
    return DailyPriceInfo(
        ticker=ticker,
        date=trade_date,
        open=Decimal(str(row["Open"])),
        high=Decimal(str(row["High"])),
        low=Decimal(str(row["Low"])),
        close=close,
        adjusted_close=close,
        volume=volume,
        # FinanceDataReader's per-ticker quote has no trading-value column —
        # approximated the same way FakePriceDataSource does.
        trading_value=close * volume,
        market_cap=None,
        halted=False,
    )


class PykrxPriceDataSource:
    """pykrx-primary daily OHLCV provider, FinanceDataReader fallback (SoT C1/C2)."""

    async def get_daily_ohlcv(self, trade_date: date) -> list[DailyPriceInfo]:
        date_str = trade_date.strftime("%Y%m%d")
        try:
            stock_df = await _fetch_with_retry(
                pykrx_stock.get_market_ohlcv, date_str, market="ALL"
            )
            etf_df = await _fetch_with_retry(pykrx_stock.get_etf_ohlcv_by_ticker, date_str)
        except Exception:
            logger.warning(
                "pykrx daily OHLCV fetch exhausted retries; falling back to FinanceDataReader",
                exc_info=True,
            )
            return await self._get_daily_ohlcv_via_fdr(trade_date)
        bars = [
            _ohlcv_row_to_bar(str(ticker), row, trade_date) for ticker, row in stock_df.iterrows()
        ]
        bars.extend(
            _ohlcv_row_to_bar(str(ticker), row, trade_date) for ticker, row in etf_df.iterrows()
        )
        return bars

    async def _get_daily_ohlcv_via_fdr(self, trade_date: date) -> list[DailyPriceInfo]:
        stock_listing = await asyncio.to_thread(fdr.StockListing, "KRX")
        etf_listing = await asyncio.to_thread(fdr.StockListing, "ETF/KR")
        codes = [*stock_listing["Code"], *etf_listing["Symbol"]]
        bars: list[DailyPriceInfo] = []
        for code in codes:
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
            try:
                history = await asyncio.to_thread(fdr.DataReader, code, trade_date, trade_date)
            except Exception:
                logger.warning("FinanceDataReader fallback failed for %s", code, exc_info=True)
                continue
            if history.empty:
                continue
            bars.append(_fdr_row_to_bar(code, history.iloc[0], trade_date))
        return bars
