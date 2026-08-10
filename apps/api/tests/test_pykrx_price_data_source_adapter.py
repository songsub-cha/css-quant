"""``PykrxPriceDataSource`` (SoT C1/C2 — adapters).

Monkeypatches ``pykrx_stock.get_market_ohlcv``/``fdr.StockListing``/
``fdr.DataReader`` — the exact call points ``src.adapters.data_sources``
uses — rather than hitting the network, same rationale as
``test_pykrx_data_source_adapter.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import FinanceDataReader as fdr
import pandas as pd
import pytest
from pykrx import stock as pykrx_stock

from src.adapters.data_sources import PykrxPriceDataSource

_TRADE_DATE = date(2026, 7, 29)


async def _no_op_sleep(_seconds: float) -> None:
    return None


def _bulk_ohlcv_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "시가": [71000],
            "고가": [71500],
            "저가": [70500],
            "종가": [71200],
            "거래량": [15_000_000],
            "거래대금": [1_068_000_000_000],
            "등락률": [0.28],
        },
        index=pd.Index(["005930"], name="티커"),
    )


def _bulk_etf_ohlcv_df() -> pd.DataFrame:
    # Includes columns absent from the stock bulk frame (NAV/기초지수) to prove
    # ``_ohlcv_row_to_bar``'s key-based column access is unaffected by them.
    return pd.DataFrame(
        {
            "시가": [35000],
            "고가": [35200],
            "저가": [34800],
            "종가": [35100],
            "거래량": [2_000_000],
            "거래대금": [70_000_000_000],
            "NAV": [35050.0],
            "기초지수": [350.5],
        },
        index=pd.Index(["069500"], name="티커"),
    )


def _bulk_market_cap_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"시가총액": [425_000_000_000_000]},
        index=pd.Index(["005930"], name="티커"),
    )


def test_get_daily_ohlcv_merges_stock_and_etf_bulk_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def get_market_ohlcv(date_str: str, market: str) -> pd.DataFrame:
        captured["stock_date_str"] = date_str
        captured["stock_market"] = market
        captured["stock_calls"] = captured.get("stock_calls", 0) + 1  # type: ignore[operator]
        return _bulk_ohlcv_df()

    def get_etf_ohlcv_by_ticker(date_str: str) -> pd.DataFrame:
        captured["etf_date_str"] = date_str
        captured["etf_calls"] = captured.get("etf_calls", 0) + 1  # type: ignore[operator]
        return _bulk_etf_ohlcv_df()

    def get_market_cap_by_ticker(date_str: str, market: str) -> pd.DataFrame:
        captured["cap_date_str"] = date_str
        captured["cap_market"] = market
        captured["cap_calls"] = captured.get("cap_calls", 0) + 1  # type: ignore[operator]
        return _bulk_market_cap_df()

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv", get_market_ohlcv)
    monkeypatch.setattr(pykrx_stock, "get_etf_ohlcv_by_ticker", get_etf_ohlcv_by_ticker)
    monkeypatch.setattr(pykrx_stock, "get_market_cap_by_ticker", get_market_cap_by_ticker)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    source = PykrxPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert captured == {
        "stock_date_str": "20260729",
        "stock_market": "ALL",
        "stock_calls": 1,
        "etf_date_str": "20260729",
        "etf_calls": 1,
        "cap_date_str": "20260729",
        "cap_market": "ALL",
        "cap_calls": 1,
    }
    assert {b.ticker for b in bars} == {"005930", "069500"}
    samsung = next(b for b in bars if b.ticker == "005930")
    assert samsung.date == _TRADE_DATE
    assert samsung.open == Decimal("71000")
    assert samsung.close == Decimal("71200")
    assert samsung.adjusted_close == Decimal("71200")
    assert samsung.volume == 15_000_000
    assert samsung.trading_value == Decimal("1068000000000")
    assert samsung.market_cap == Decimal("425000000000000")
    assert samsung.halted is False

    kodex = next(b for b in bars if b.ticker == "069500")
    assert kodex.date == _TRADE_DATE
    assert kodex.open == Decimal("35000")
    assert kodex.close == Decimal("35100")
    assert kodex.adjusted_close == Decimal("35100")
    assert kodex.volume == 2_000_000
    assert kodex.trading_value == Decimal("70000000000")
    assert kodex.market_cap is None
    assert kodex.halted is False


def test_get_daily_ohlcv_returns_empty_list_on_market_holiday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty bulk result (e.g. a market holiday) is not a fetch failure —
    it must not trigger retries or the FDR fallback, and the market-cap bulk
    call must be skipped entirely since there are no stock bars to enrich."""
    call_count = {"stock": 0, "etf": 0, "cap": 0}

    def get_market_ohlcv(date_str: str, market: str) -> pd.DataFrame:
        call_count["stock"] += 1
        return pd.DataFrame()

    def get_etf_ohlcv_by_ticker(date_str: str) -> pd.DataFrame:
        call_count["etf"] += 1
        return pd.DataFrame()

    def get_market_cap_by_ticker(date_str: str, market: str) -> pd.DataFrame:
        call_count["cap"] += 1
        return pd.DataFrame()

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv", get_market_ohlcv)
    monkeypatch.setattr(pykrx_stock, "get_etf_ohlcv_by_ticker", get_etf_ohlcv_by_ticker)
    monkeypatch.setattr(pykrx_stock, "get_market_cap_by_ticker", get_market_cap_by_ticker)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    source = PykrxPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert bars == []
    assert call_count == {"stock": 1, "etf": 1, "cap": 0}


def test_get_daily_ohlcv_falls_back_to_fdr_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}

    def always_fails(date_str: str, market: str) -> pd.DataFrame:
        call_count["n"] += 1
        raise RuntimeError("pykrx scrape failed")

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv", always_fails)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    stock_listing = pd.DataFrame({"Code": ["005930", "000660"]})
    etf_listing = pd.DataFrame({"Symbol": ["069500"]})

    def stock_listing_by_market(market: str) -> pd.DataFrame:
        if market == "ETF/KR":
            return etf_listing
        return stock_listing

    monkeypatch.setattr(fdr, "StockListing", stock_listing_by_market)

    def data_reader(code: str, start: date, end: date) -> pd.DataFrame:
        if code == "005930":
            return pd.DataFrame(
                {
                    "Open": [71000],
                    "High": [71500],
                    "Low": [70500],
                    "Close": [71200],
                    "Volume": [15_000_000],
                }
            )
        if code == "069500":
            return pd.DataFrame(
                {
                    "Open": [35000],
                    "High": [35200],
                    "Low": [34800],
                    "Close": [35100],
                    "Volume": [2_000_000],
                }
            )
        raise RuntimeError("FDR also failed for this ticker")

    monkeypatch.setattr(fdr, "DataReader", data_reader)

    source = PykrxPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert call_count["n"] == 3
    assert {b.ticker for b in bars} == {"005930", "069500"}
    samsung = next(b for b in bars if b.ticker == "005930")
    assert samsung.date == _TRADE_DATE
    assert samsung.close == Decimal("71200")
    assert samsung.adjusted_close == Decimal("71200")
    assert samsung.trading_value == Decimal("71200") * 15_000_000

    kodex = next(b for b in bars if b.ticker == "069500")
    assert kodex.date == _TRADE_DATE
    assert kodex.close == Decimal("35100")
    assert kodex.adjusted_close == Decimal("35100")
    assert kodex.trading_value == Decimal("35100") * 2_000_000


def test_get_daily_ohlcv_degrades_to_none_market_cap_when_cap_fetch_exhausts_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A market-cap-only failure must not drag down an otherwise-successful
    OHLCV fetch: stock/ETF bars still come back (no re-fetch, no FDR
    fallback), just with ``market_cap=None``."""
    call_count = {"stock": 0, "etf": 0, "cap": 0}

    def get_market_ohlcv(date_str: str, market: str) -> pd.DataFrame:
        call_count["stock"] += 1
        return _bulk_ohlcv_df()

    def get_etf_ohlcv_by_ticker(date_str: str) -> pd.DataFrame:
        call_count["etf"] += 1
        return _bulk_etf_ohlcv_df()

    def get_market_cap_by_ticker(date_str: str, market: str) -> pd.DataFrame:
        call_count["cap"] += 1
        raise RuntimeError("pykrx market cap scrape failed")

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv", get_market_ohlcv)
    monkeypatch.setattr(pykrx_stock, "get_etf_ohlcv_by_ticker", get_etf_ohlcv_by_ticker)
    monkeypatch.setattr(pykrx_stock, "get_market_cap_by_ticker", get_market_cap_by_ticker)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    source = PykrxPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert call_count == {"stock": 1, "etf": 1, "cap": 3}
    assert {b.ticker for b in bars} == {"005930", "069500"}
    assert all(b.market_cap is None for b in bars)
