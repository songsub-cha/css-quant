"""Minimal direct client for the KRX 정보데이터시스템 ticker-search endpoint (SoT C1).

This is the documented fallback for ticker master when ``PykrxDataSource``
(``src/adapters/data_sources.py``) exhausts its retries. It calls the same
public JSON endpoint (`finder_stkisu`, the autocomplete search KRX's own
정보데이터시스템 site uses) that ``pykrx`` itself wraps internally — hitting it
directly here means a pykrx *library* parsing bug (its scraping layer
breaking against a KRX response-shape change) doesn't take down the fallback
along with the primary source, which importing ``pykrx`` for the fallback
too would risk.

Stock tickers only: this finder endpoint has no ETF listing, matching SoT
C1's data-source table, where only the 종목 마스터 (stock ticker master) row
has a documented KRX 정보데이터시스템 fallback — ETF master collection is out
of this issue's scope beyond what ``PykrxDataSource`` already covers.
"""

from __future__ import annotations

import httpx

from src.domain.asset import AssetType, Exchange, TickerInfo

_FINDER_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
_FINDER_BLD = "dbms/comm/finder/finder_stkisu"
_REQUEST_TIMEOUT_SECONDS = 10.0
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
}
_MARKET_NAME_TO_EXCHANGE = {"유가증권": Exchange.KOSPI, "코스닥": Exchange.KOSDAQ}


def fetch_ticker_master() -> list[TickerInfo]:
    """Blocking HTTP call — callers must run this via ``asyncio.to_thread``.

    Rows whose ``marketName`` isn't KOSPI/KOSDAQ (e.g. KONEX) are skipped —
    ``Exchange`` has no member for them.
    """
    response = httpx.post(
        _FINDER_URL,
        headers=_HEADERS,
        data={
            "bld": _FINDER_BLD,
            "locale": "ko_KR",
            "mktsel": "ALL",
            "searchText": "",
            "typeNo": 0,
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    rows = response.json()["block1"]

    tickers: list[TickerInfo] = []
    for row in rows:
        exchange = _MARKET_NAME_TO_EXCHANGE.get(row["marketName"])
        if exchange is None:
            continue
        tickers.append(
            TickerInfo(
                ticker=row["short_code"],
                name=row["codeName"],
                exchange=exchange,
                asset_type=AssetType.STOCK,
            )
        )
    return tickers
