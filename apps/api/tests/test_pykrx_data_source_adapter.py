"""``PykrxDataSource`` (SoT C1/C2 — adapters).

pykrx/FinanceDataReader are scraping libraries, so every test here
monkeypatches the exact call points ``src.adapters.data_sources`` uses
(``pykrx_stock.*``, ``krx_fallback.fetch_ticker_master``) rather than hitting
the network — the plan explicitly excludes real-network CI smoke tests.
``asyncio.sleep`` is monkeypatched to a no-op so retry backoff / inter-request
delay don't slow the suite down.
"""

from __future__ import annotations

import asyncio

import pytest
from pykrx import stock as pykrx_stock

from src.adapters import krx_fallback
from src.adapters.data_sources import PykrxDataSource, _fetch_with_retry
from src.domain.asset import AssetType, Exchange, TickerInfo

_KOSPI_TICKERS = {"005930": "삼성전자", "000660": "SK하이닉스"}
_KOSDAQ_TICKERS = {"086520": "에코프로"}
_ETF_TICKERS = {"069500": "KODEX 200"}


async def _no_op_sleep(_seconds: float) -> None:
    return None


def _install_pykrx_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_market_ticker_list(market: str) -> list[str]:
        return {"KOSPI": list(_KOSPI_TICKERS), "KOSDAQ": list(_KOSDAQ_TICKERS)}[market]

    def get_market_ticker_name(ticker: str) -> str:
        return {**_KOSPI_TICKERS, **_KOSDAQ_TICKERS}[ticker]

    def get_etf_ticker_list() -> list[str]:
        return list(_ETF_TICKERS)

    def get_etf_ticker_name(ticker: str) -> str:
        return _ETF_TICKERS[ticker]

    monkeypatch.setattr(pykrx_stock, "get_market_ticker_list", get_market_ticker_list)
    monkeypatch.setattr(pykrx_stock, "get_market_ticker_name", get_market_ticker_name)
    monkeypatch.setattr(pykrx_stock, "get_etf_ticker_list", get_etf_ticker_list)
    monkeypatch.setattr(pykrx_stock, "get_etf_ticker_name", get_etf_ticker_name)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)


def test_list_tickers_returns_stocks_and_etfs_from_pykrx(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pykrx_stubs(monkeypatch)
    source = PykrxDataSource()

    tickers = asyncio.run(source.list_tickers())

    assert set(tickers) == {
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
    }


def test_list_tickers_falls_back_to_krx_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}

    def always_fails(market: str) -> list[str]:
        call_count["n"] += 1
        raise RuntimeError("KRX scrape failed")

    fallback_tickers = [
        TickerInfo(
            ticker="005930", name="삼성전자", exchange=Exchange.KOSPI, asset_type=AssetType.STOCK
        )
    ]

    monkeypatch.setattr(pykrx_stock, "get_market_ticker_list", always_fails)
    monkeypatch.setattr(krx_fallback, "fetch_ticker_master", lambda: fallback_tickers)
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    source = PykrxDataSource()
    result = asyncio.run(source.list_tickers())

    assert result == fallback_tickers
    assert call_count["n"] == 3


def test_fetch_with_retry_succeeds_after_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = asyncio.run(_fetch_with_retry(flaky))

    assert result == "ok"
    assert calls["n"] == 3


def test_fetch_with_retry_raises_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    calls = {"n": 0}

    def always_fails() -> str:
        calls["n"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(_fetch_with_retry(always_fails))

    assert calls["n"] == 3
