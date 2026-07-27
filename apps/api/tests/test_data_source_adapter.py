import asyncio

from src.adapters.data_sources import FakeDataSource
from src.domain.asset import Exchange, TickerInfo


def test_fake_data_source_returns_expected_tickers() -> None:
    source = FakeDataSource()

    tickers = asyncio.run(source.list_tickers())

    assert len(tickers) == 3
    assert all(isinstance(t, TickerInfo) for t in tickers)
    assert tickers == [
        TickerInfo(ticker="005930", name="삼성전자", exchange=Exchange.KOSPI),
        TickerInfo(ticker="000660", name="SK하이닉스", exchange=Exchange.KOSPI),
        TickerInfo(ticker="086520", name="에코프로", exchange=Exchange.KOSDAQ),
    ]


def test_fake_data_source_is_deterministic() -> None:
    source = FakeDataSource()

    first = asyncio.run(source.list_tickers())
    second = asyncio.run(source.list_tickers())

    assert first == second
