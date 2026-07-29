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
            "시가": [71000, 35000],
            "고가": [71500, 35200],
            "저가": [70500, 34800],
            "종가": [71200, 35100],
            "거래량": [15_000_000, 2_000_000],
            "거래대금": [1_068_000_000_000, 70_000_000_000],
            "등락률": [0.28, 0.29],
        },
        index=pd.Index(["005930", "069500"], name="티커"),
    )


def test_get_daily_ohlcv_uses_one_bulk_pykrx_call_for_the_whole_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def get_market_ohlcv(date_str: str, market: str) -> pd.DataFrame:
        captured["date_str"] = date_str
        captured["market"] = market
        captured["calls"] = captured.get("calls", 0) + 1  # type: ignore[operator]
        return _bulk_ohlcv_df()

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv", get_market_ohlcv)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    source = PykrxPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert captured == {"date_str": "20260729", "market": "ALL", "calls": 1}
    assert {b.ticker for b in bars} == {"005930", "069500"}
    samsung = next(b for b in bars if b.ticker == "005930")
    assert samsung.date == _TRADE_DATE
    assert samsung.open == Decimal("71000")
    assert samsung.close == Decimal("71200")
    assert samsung.adjusted_close == Decimal("71200")
    assert samsung.volume == 15_000_000
    assert samsung.trading_value == Decimal("1068000000000")
    assert samsung.market_cap is None
    assert samsung.halted is False


def test_get_daily_ohlcv_returns_empty_list_on_market_holiday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty bulk result (e.g. a market holiday) is not a fetch failure —
    it must not trigger retries or the FDR fallback."""
    call_count = {"n": 0}

    def get_market_ohlcv(date_str: str, market: str) -> pd.DataFrame:
        call_count["n"] += 1
        return pd.DataFrame()

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv", get_market_ohlcv)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    source = PykrxPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert bars == []
    assert call_count["n"] == 1


def test_get_daily_ohlcv_falls_back_to_fdr_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}

    def always_fails(date_str: str, market: str) -> pd.DataFrame:
        call_count["n"] += 1
        raise RuntimeError("pykrx scrape failed")

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv", always_fails)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    listing = pd.DataFrame({"Code": ["005930", "000660"]})
    monkeypatch.setattr(fdr, "StockListing", lambda market: listing)

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
        raise RuntimeError("FDR also failed for this ticker")

    monkeypatch.setattr(fdr, "DataReader", data_reader)

    source = PykrxPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert call_count["n"] == 3
    assert len(bars) == 1
    bar = bars[0]
    assert bar.ticker == "005930"
    assert bar.date == _TRADE_DATE
    assert bar.close == Decimal("71200")
    assert bar.adjusted_close == Decimal("71200")
    assert bar.trading_value == Decimal("71200") * 15_000_000
