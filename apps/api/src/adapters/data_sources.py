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
into thousands of scraping requests. Daily market cap (SoT A6.1/C1) follows
the same bulk-call pattern (``get_market_cap_by_ticker(date, market="ALL")``)
but is wired to stock bars only — ETFs are excluded from the AI score
universe (ADR 0011), and that exclusion is enforced structurally by never
passing the market-cap map into the ETF bar-building call, not by relying on
what the pykrx endpoint happens to return.

``FakeIndexPriceDataSource``/``PykrxIndexPriceDataSource`` (SoT A6.2/A6.3)
follow the same fake-by-default/retry pattern for KOSPI/VKOSPI index daily
OHLCV — a separate pair from the ticker/price sources above because an index
has no ``assets`` row and pykrx exposes it through a different, per-ticker
endpoint (``get_index_ohlcv_by_date``) rather than a bulk all-tickers one.
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
from src.domain.index_price import IndexCode, IndexPriceInfo
from src.domain.market_price import DailyPriceInfo

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_INITIAL_BACKOFF_SECONDS = 1.0
_REQUEST_DELAY_SECONDS = 0.2

# pykrx's own get_index_ohlcv_by_date docstring example confirms "1001" as
# the KOSPI index ticker. Neither pykrx nor FinanceDataReader documents a
# VKOSPI ticker anywhere in their source (grepped both site-packages trees
# for "vkospi"/"변동성" — zero hits), so it is resolved dynamically by name
# match at collection time (PykrxIndexPriceDataSource._resolve_vkospi_ticker)
# instead of risking a hardcoded, unverified guess.
_KOSPI_INDEX_TICKER = "1001"
_VKOSPI_NAME_HINT = "변동성"

_FAKE_INDEX_OHLCV: tuple[tuple[IndexCode, int, int, int, int, int], ...] = (
    (IndexCode.KOSPI, 2_650, 2_670, 2_640, 2_665, 450_000_000),
    (IndexCode.VKOSPI, 18, 19, 17, 18, 1),
)

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


class FakeIndexPriceDataSource:
    """Deterministic stand-in for a real KOSPI/VKOSPI index OHLCV provider.

    Never calls out to the network. Always returns the same fixed sample for
    both indices, stamped with the requested ``trade_date`` — same rationale
    as ``FakePriceDataSource``.
    """

    async def get_daily_ohlcv(self, trade_date: date) -> list[IndexPriceInfo]:
        return [
            IndexPriceInfo(
                index_code=index_code,
                date=trade_date,
                open=Decimal(open_),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=volume,
                trading_value=Decimal(close * volume),
            )
            for index_code, open_, high, low, close, volume in _FAKE_INDEX_OHLCV
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


def _ohlcv_row_to_bar(
    ticker: str, row: Any, trade_date: date, market_cap: Decimal | None = None
) -> DailyPriceInfo:
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
        market_cap=market_cap,
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


async def _fetch_market_caps(date_str: str) -> dict[str, Decimal]:
    """Bulk stock market-cap lookup for one trading day (SoT A6.1/C1).

    A failure here must not drag down an otherwise-successful OHLCV fetch —
    retries are exhausted the same way as the OHLCV bulk calls, but on final
    failure this degrades to an empty map (all bars fall back to
    ``market_cap=None``) instead of propagating and triggering the FDR
    fallback path.
    """
    try:
        df = await _fetch_with_retry(pykrx_stock.get_market_cap_by_ticker, date_str, market="ALL")
    except Exception:
        logger.warning(
            "pykrx market cap fetch exhausted retries; degrading to market_cap=None",
            exc_info=True,
        )
        return {}
    return {str(ticker): Decimal(str(row["시가총액"])) for ticker, row in df.iterrows()}


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

        market_caps: dict[str, Decimal] = {}
        if not stock_df.empty:
            market_caps = await _fetch_market_caps(date_str)

        bars = [
            _ohlcv_row_to_bar(str(ticker), row, trade_date, market_caps.get(str(ticker)))
            for ticker, row in stock_df.iterrows()
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


def _index_ohlcv_row_to_bar(index_code: IndexCode, row: Any, trade_date: date) -> IndexPriceInfo:
    return IndexPriceInfo(
        index_code=index_code,
        date=trade_date,
        open=Decimal(str(row["시가"])),
        high=Decimal(str(row["고가"])),
        low=Decimal(str(row["저가"])),
        close=Decimal(str(row["종가"])),
        volume=int(row["거래량"]),
        trading_value=Decimal(str(row["거래대금"])),
    )


def _fdr_index_row_to_bar(index_code: IndexCode, row: Any, trade_date: date) -> IndexPriceInfo:
    volume = int(row["Volume"])
    return IndexPriceInfo(
        index_code=index_code,
        date=trade_date,
        open=Decimal(str(row["Open"])),
        high=Decimal(str(row["High"])),
        low=Decimal(str(row["Low"])),
        close=Decimal(str(row["Close"])),
        volume=volume,
        # FinanceDataReader's per-ticker quote has no trading-value column —
        # approximated the same way _fdr_row_to_bar does for market_prices.
        trading_value=Decimal(str(row["Close"])) * volume,
    )


class PykrxIndexPriceDataSource:
    """pykrx-primary KOSPI/VKOSPI daily OHLCV provider (SoT A6.2/A6.3/C1/C2).

    Only two tickers are ever fetched, so — unlike ``PykrxPriceDataSource``
    — each index gets its own per-index ``get_index_ohlcv_by_date`` call
    rather than a bulk all-tickers query; SoT C2's bulk-call concern (turning
    one run into thousands of scraping requests) does not apply at this
    scale.

    KOSPI retries exhausted -> FinanceDataReader (``KS11``) fallback, mirroring
    ``PykrxPriceDataSource``. VKOSPI has no such fallback yet — SoT C1 names
    "KRX" as VKOSPI's secondary source, but that direct endpoint isn't wired
    anywhere in this codebase (``krx_fallback.py`` only covers ticker
    master) and is out of this issue's scope; VKOSPI retries exhausted means
    that day's VKOSPI bar is simply omitted (SoT A6.4 — a single missing
    data point is held back, not treated as a whole-sync failure).
    """

    def __init__(self) -> None:
        self._vkospi_ticker: str | None = None

    async def get_daily_ohlcv(self, trade_date: date) -> list[IndexPriceInfo]:
        bars: list[IndexPriceInfo] = []

        kospi_bar = await self._get_kospi_bar(trade_date)
        if kospi_bar is not None:
            bars.append(kospi_bar)

        vkospi_bar = await self._get_vkospi_bar(trade_date)
        if vkospi_bar is not None:
            bars.append(vkospi_bar)

        return bars

    async def _get_kospi_bar(self, trade_date: date) -> IndexPriceInfo | None:
        date_str = trade_date.strftime("%Y%m%d")
        try:
            df = await _fetch_with_retry(
                pykrx_stock.get_index_ohlcv_by_date, date_str, date_str, _KOSPI_INDEX_TICKER
            )
        except Exception:
            logger.warning(
                "pykrx KOSPI index OHLCV fetch exhausted retries;"
                " falling back to FinanceDataReader",
                exc_info=True,
            )
            return await self._get_kospi_bar_via_fdr(trade_date)
        if df.empty:
            return None
        return _index_ohlcv_row_to_bar(IndexCode.KOSPI, df.iloc[0], trade_date)

    async def _get_kospi_bar_via_fdr(self, trade_date: date) -> IndexPriceInfo | None:
        try:
            history = await asyncio.to_thread(fdr.DataReader, "KS11", trade_date, trade_date)
        except Exception:
            logger.warning("FinanceDataReader KOSPI fallback failed", exc_info=True)
            return None
        if history.empty:
            return None
        return _fdr_index_row_to_bar(IndexCode.KOSPI, history.iloc[0], trade_date)

    async def _get_vkospi_bar(self, trade_date: date) -> IndexPriceInfo | None:
        date_str = trade_date.strftime("%Y%m%d")
        try:
            ticker = await self._resolve_vkospi_ticker()
            df = await _fetch_with_retry(
                pykrx_stock.get_index_ohlcv_by_date, date_str, date_str, ticker
            )
        except Exception:
            logger.warning(
                "VKOSPI index OHLCV fetch exhausted retries (or ticker unresolved);"
                " omitting from today's result",
                exc_info=True,
            )
            return None
        if df.empty:
            return None
        return _index_ohlcv_row_to_bar(IndexCode.VKOSPI, df.iloc[0], trade_date)

    async def _resolve_vkospi_ticker(self) -> str:
        """Look up VKOSPI's pykrx ticker by name match rather than a hardcoded constant.

        Neither pykrx nor FinanceDataReader documents a stable VKOSPI ticker
        anywhere (unlike KOSPI's ``"1001"``, confirmed by pykrx's own
        ``get_index_ohlcv_by_date`` docstring example) — hardcoding an
        unverified guess risks silently collecting the wrong index under the
        VKOSPI label. Resolved once per instance and cached; a failed lookup
        is retried on the next call instead of caching the failure.
        """
        if self._vkospi_ticker is not None:
            return self._vkospi_ticker
        tickers = await _fetch_with_retry(pykrx_stock.get_index_ticker_list, market="KRX")
        for raw_ticker in tickers:
            ticker = str(raw_ticker)
            name = await _fetch_with_retry(pykrx_stock.get_index_ticker_name, ticker)
            if _VKOSPI_NAME_HINT in name:
                self._vkospi_ticker = ticker
                return ticker
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
        raise LookupError("VKOSPI ticker not found in KRX index ticker list")
