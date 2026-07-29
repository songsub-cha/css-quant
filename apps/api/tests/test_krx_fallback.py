"""``krx_fallback.fetch_ticker_master`` (SoT C1 — ticker master fallback).

Monkeypatches ``httpx.post`` rather than hitting data.krx.co.kr — same
network-free rationale as the pykrx adapter tests.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.adapters import krx_fallback
from src.domain.asset import AssetType, Exchange, TickerInfo


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_fetch_ticker_master_parses_stock_rows_and_skips_non_kospi_kosdaq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "block1": [
            {"short_code": "005930", "codeName": "삼성전자", "marketName": "유가증권"},
            {"short_code": "035720", "codeName": "카카오", "marketName": "코스닥"},
            {"short_code": "900110", "codeName": "이스트아시아", "marketName": "코넥스"},
        ]
    }
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx, "post", fake_post)

    tickers = krx_fallback.fetch_ticker_master()

    assert captured["url"] == krx_fallback._FINDER_URL
    assert captured["data"]["bld"] == krx_fallback._FINDER_BLD
    assert tickers == [
        TickerInfo(
            ticker="005930", name="삼성전자", exchange=Exchange.KOSPI, asset_type=AssetType.STOCK
        ),
        TickerInfo(
            ticker="035720", name="카카오", exchange=Exchange.KOSDAQ, asset_type=AssetType.STOCK
        ),
    ]


def test_fetch_ticker_master_propagates_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingResponse:
        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

        def json(self) -> dict[str, Any]:
            raise AssertionError("should not be called when raise_for_status raises")

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _FailingResponse())

    with pytest.raises(httpx.HTTPStatusError):
        krx_fallback.fetch_ticker_master()
