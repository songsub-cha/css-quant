"""``sync_financial_statements`` (SoT C1/A6.1/A6.7.2, services layer).

No DB container in this environment: exercised against
``conftest.FakeAssetRepository``/``FakeFinancialStatementRepository``, same
isolation approach as ``test_price_sync.py``. Uses ``asyncio.run`` directly
(no pytest-asyncio dependency in this project).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from src.adapters.dart_financial_data_source import DartSystemicError
from src.domain.asset import AssetType, Exchange, Market
from src.domain.financial_statement import ConsolidatedType, FinancialStatementInfo, FiscalQuarter
from src.services.financial_statement_sync import sync_financial_statements

from .conftest import FakeAssetRepository, FakeFinancialStatementRepository


class _StubFinancialStatementDataSource:
    def __init__(self, statements: list[FinancialStatementInfo]) -> None:
        self._statements = statements
        self.requested_tickers: list[str] | None = None

    async def get_quarterly_statements(
        self, tickers: list[str], fiscal_year: int, fiscal_quarter: FiscalQuarter
    ) -> list[FinancialStatementInfo]:
        self.requested_tickers = tickers
        return self._statements


class _SystemicErrorDataSource:
    async def get_quarterly_statements(
        self, tickers: list[str], fiscal_year: int, fiscal_quarter: FiscalQuarter
    ) -> list[FinancialStatementInfo]:
        raise DartSystemicError("registered key rejected")


def _statement(ticker: str, rcept_no: str = "20260514000001") -> FinancialStatementInfo:
    return FinancialStatementInfo(
        ticker=ticker,
        fiscal_year=2025,
        fiscal_quarter=FiscalQuarter.ANNUAL,
        consolidated_type=ConsolidatedType.CFS,
        revenue=Decimal(1_000),
        operating_income=Decimal(200),
        net_income=Decimal(150),
        total_assets=Decimal(5_000),
        total_liabilities=Decimal(2_000),
        total_equity=Decimal(3_000),
        disclosed_at=date(2026, 3, 31),
        rcept_no=rcept_no,
    )


async def _seed_active_asset(
    asset_repo: FakeAssetRepository, ticker: str, asset_type: AssetType = AssetType.STOCK
) -> None:
    await asset_repo.upsert_active(
        ticker=ticker,
        name="Test Asset",
        market=Market.KR,
        asset_type=asset_type,
        exchange=Exchange.KOSPI,
    )


def test_sync_financial_statements_upserts_statement_for_known_ticker() -> None:
    asset_repo = FakeAssetRepository()
    statement_repo = FakeFinancialStatementRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    asset = asyncio.run(asset_repo.get_active_by_ticker("005930", Market.KR))
    assert asset is not None
    source = _StubFinancialStatementDataSource([_statement("005930")])

    result = asyncio.run(
        sync_financial_statements(source, asset_repo, statement_repo, 2025, FiscalQuarter.ANNUAL)
    )

    assert result.synced == 1
    assert result.skipped_tickers == ()
    assert len(statement_repo.statements) == 1
    assert statement_repo.statements[0].asset_id == asset.id


def test_sync_financial_statements_only_requests_stock_tickers_excluding_etf() -> None:
    asset_repo = FakeAssetRepository()
    statement_repo = FakeFinancialStatementRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930", AssetType.STOCK))
    asyncio.run(_seed_active_asset(asset_repo, "069500", AssetType.ETF))
    source = _StubFinancialStatementDataSource([])

    asyncio.run(
        sync_financial_statements(source, asset_repo, statement_repo, 2025, FiscalQuarter.ANNUAL)
    )

    assert source.requested_tickers == ["005930"]


def test_sync_financial_statements_skips_ticker_not_found_in_assets() -> None:
    asset_repo = FakeAssetRepository()
    statement_repo = FakeFinancialStatementRepository()
    source = _StubFinancialStatementDataSource([_statement("999999")])

    result = asyncio.run(
        sync_financial_statements(source, asset_repo, statement_repo, 2025, FiscalQuarter.ANNUAL)
    )

    assert result.synced == 0
    assert result.skipped_tickers == ("999999",)
    assert statement_repo.statements == []


def test_sync_financial_statements_corrected_disclosure_updates_row_in_place() -> None:
    asset_repo = FakeAssetRepository()
    statement_repo = FakeFinancialStatementRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    source_first = _StubFinancialStatementDataSource(
        [_statement("005930", rcept_no="20260514000001")]
    )
    asyncio.run(
        sync_financial_statements(
            source_first, asset_repo, statement_repo, 2025, FiscalQuarter.ANNUAL
        )
    )

    source_second = _StubFinancialStatementDataSource(
        [_statement("005930", rcept_no="20260601000002")]
    )
    result = asyncio.run(
        sync_financial_statements(
            source_second, asset_repo, statement_repo, 2025, FiscalQuarter.ANNUAL
        )
    )

    assert result.synced == 1
    assert len(statement_repo.statements) == 1
    assert statement_repo.statements[0].rcept_no == "20260601000002"


def test_sync_financial_statements_propagates_dart_systemic_error() -> None:
    """DartSystemicError must not be swallowed into a partial/empty success result."""
    asset_repo = FakeAssetRepository()
    statement_repo = FakeFinancialStatementRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    source = _SystemicErrorDataSource()

    with pytest.raises(DartSystemicError):
        asyncio.run(
            sync_financial_statements(
                source, asset_repo, statement_repo, 2025, FiscalQuarter.ANNUAL
            )
        )

    assert statement_repo.statements == []
