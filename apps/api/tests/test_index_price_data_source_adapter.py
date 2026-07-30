"""``FakeIndexPriceDataSource``/``PykrxIndexPriceDataSource`` (SoT A6.2/A6.3/C1/C2 — adapters).

Same monkeypatch-the-call-points approach as
``test_pykrx_price_data_source_adapter.py`` — pykrx/FinanceDataReader are
scraping libraries, so tests never hit the network.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import FinanceDataReader as fdr
import pandas as pd
import pytest
from pykrx import stock as pykrx_stock

from src.adapters.data_sources import FakeIndexPriceDataSource, PykrxIndexPriceDataSource
from src.domain.index_price import IndexCode, IndexPriceInfo

_TRADE_DATE = date(2026, 7, 29)
_VKOSPI_TICKER = "1035"


async def _no_op_sleep(_seconds: float) -> None:
    return None


def test_fake_index_price_data_source_returns_expected_indices() -> None:
    source = FakeIndexPriceDataSource()

    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert len(bars) == 2
    assert all(isinstance(b, IndexPriceInfo) for b in bars)
    assert {b.index_code for b in bars} == {IndexCode.KOSPI, IndexCode.VKOSPI}
    assert all(b.date == _TRADE_DATE for b in bars)


def test_fake_index_price_data_source_is_deterministic() -> None:
    source = FakeIndexPriceDataSource()

    first = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))
    second = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert first == second


def _index_ohlcv_df(
    open_: int, high: int, low: int, close: int, volume: int, value: int
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "시가": [open_],
            "고가": [high],
            "저가": [low],
            "종가": [close],
            "거래량": [volume],
            "거래대금": [value],
        },
        index=pd.Index([pd.Timestamp(_TRADE_DATE)], name="날짜"),
    )


def _install_vkospi_ticker_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_index_ticker_list(market: str) -> list[str]:
        assert market == "KRX"
        return ["1001", _VKOSPI_TICKER]

    def get_index_ticker_name(ticker: str) -> str:
        return {"1001": "코스피", _VKOSPI_TICKER: "코스피 200 변동성지수"}[ticker]

    monkeypatch.setattr(pykrx_stock, "get_index_ticker_list", get_index_ticker_list)
    monkeypatch.setattr(pykrx_stock, "get_index_ticker_name", get_index_ticker_name)


def test_get_daily_ohlcv_returns_kospi_and_vkospi_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_vkospi_ticker_stub(monkeypatch)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    calls: list[tuple[str, str, str]] = []

    def get_index_ohlcv_by_date(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
        calls.append((fromdate, todate, ticker))
        if ticker == "1001":
            return _index_ohlcv_df(2650, 2670, 2640, 2665, 450_000_000, 8_000_000_000_000)
        return _index_ohlcv_df(18, 19, 17, 18, 1, 1)

    monkeypatch.setattr(pykrx_stock, "get_index_ohlcv_by_date", get_index_ohlcv_by_date)

    source = PykrxIndexPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert {b.index_code for b in bars} == {IndexCode.KOSPI, IndexCode.VKOSPI}
    kospi = next(b for b in bars if b.index_code == IndexCode.KOSPI)
    assert kospi.date == _TRADE_DATE
    assert kospi.open == Decimal("2650")
    assert kospi.close == Decimal("2665")
    assert kospi.volume == 450_000_000
    assert kospi.trading_value == Decimal("8000000000000")

    vkospi = next(b for b in bars if b.index_code == IndexCode.VKOSPI)
    assert vkospi.close == Decimal("18")
    assert ("20260729", "20260729", "1001") in calls
    assert ("20260729", "20260729", _VKOSPI_TICKER) in calls


def test_get_daily_ohlcv_kospi_falls_back_to_fdr_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_vkospi_ticker_stub(monkeypatch)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    call_count = {"n": 0}

    def get_index_ohlcv_by_date(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
        if ticker == "1001":
            call_count["n"] += 1
            raise RuntimeError("pykrx scrape failed")
        return _index_ohlcv_df(18, 19, 17, 18, 1, 1)

    monkeypatch.setattr(pykrx_stock, "get_index_ohlcv_by_date", get_index_ohlcv_by_date)

    def data_reader(code: str, start: date, end: date) -> pd.DataFrame:
        assert code == "KS11"
        return pd.DataFrame(
            {
                "Open": [2650],
                "High": [2670],
                "Low": [2640],
                "Close": [2665],
                "Volume": [450_000_000],
            }
        )

    monkeypatch.setattr(fdr, "DataReader", data_reader)

    source = PykrxIndexPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert call_count["n"] == 3
    kospi = next(b for b in bars if b.index_code == IndexCode.KOSPI)
    assert kospi.close == Decimal("2665")
    assert kospi.trading_value == Decimal("2665") * 450_000_000


def test_get_daily_ohlcv_omits_vkospi_when_ticker_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    def get_index_ticker_list(market: str) -> list[str]:
        return ["1001"]  # no name in the list matches the VKOSPI hint

    def get_index_ticker_name(ticker: str) -> str:
        return "코스피"

    monkeypatch.setattr(pykrx_stock, "get_index_ticker_list", get_index_ticker_list)
    monkeypatch.setattr(pykrx_stock, "get_index_ticker_name", get_index_ticker_name)

    def get_index_ohlcv_by_date(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
        assert ticker == "1001"
        return _index_ohlcv_df(2650, 2670, 2640, 2665, 450_000_000, 8_000_000_000_000)

    monkeypatch.setattr(pykrx_stock, "get_index_ohlcv_by_date", get_index_ohlcv_by_date)

    source = PykrxIndexPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert {b.index_code for b in bars} == {IndexCode.KOSPI}


def test_get_daily_ohlcv_omits_vkospi_when_ohlcv_fetch_exhausts_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_vkospi_ticker_stub(monkeypatch)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    def get_index_ohlcv_by_date(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
        if ticker == "1001":
            return _index_ohlcv_df(2650, 2670, 2640, 2665, 450_000_000, 8_000_000_000_000)
        raise RuntimeError("VKOSPI scrape failed")

    monkeypatch.setattr(pykrx_stock, "get_index_ohlcv_by_date", get_index_ohlcv_by_date)

    source = PykrxIndexPriceDataSource()
    bars = asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert {b.index_code for b in bars} == {IndexCode.KOSPI}


def test_resolve_vkospi_ticker_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_vkospi_ticker_stub(monkeypatch)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    list_calls = {"n": 0}
    original_list = pykrx_stock.get_index_ticker_list

    def counting_get_index_ticker_list(market: str) -> list[str]:
        list_calls["n"] += 1
        result: list[str] = original_list(market)
        return result

    monkeypatch.setattr(pykrx_stock, "get_index_ticker_list", counting_get_index_ticker_list)

    def get_index_ohlcv_by_date(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
        return _index_ohlcv_df(18, 19, 17, 18, 1, 1)

    monkeypatch.setattr(pykrx_stock, "get_index_ohlcv_by_date", get_index_ohlcv_by_date)

    source = PykrxIndexPriceDataSource()
    asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))
    asyncio.run(source.get_daily_ohlcv(_TRADE_DATE))

    assert list_calls["n"] == 1
