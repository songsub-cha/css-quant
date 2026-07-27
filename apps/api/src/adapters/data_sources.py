"""Fake-by-default ticker master data source (SoT C1 — adapters).

SoT ADR 0004 (fake-by-default adapters) / B3: every external integration
sits behind a Protocol with a deterministic fake as the default
implementation, so the whole app runs with zero API keys/network access.
The real provider (``PykrxDataSource``, with a KRX 정보데이터시스템 fallback)
is added in a later issue behind the same ``DataSource`` interface.
"""

from __future__ import annotations

from src.domain.asset import Exchange, TickerInfo

_FAKE_TICKERS: tuple[TickerInfo, ...] = (
    TickerInfo(ticker="005930", name="삼성전자", exchange=Exchange.KOSPI),
    TickerInfo(ticker="000660", name="SK하이닉스", exchange=Exchange.KOSPI),
    TickerInfo(ticker="086520", name="에코프로", exchange=Exchange.KOSDAQ),
)


class FakeDataSource:
    """Deterministic stand-in for a real ticker-master provider.

    Never calls out to the network. Always returns the same fixed sample of
    tickers, which keeps tests and local runs reproducible without secrets.
    """

    async def list_tickers(self) -> list[TickerInfo]:
        return list(_FAKE_TICKERS)
