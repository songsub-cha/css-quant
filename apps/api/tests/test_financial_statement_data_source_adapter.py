"""``FakeFinancialStatementDataSource`` (SoT C1/A6.1 — adapters).

The real ``DartFinancialStatementDataSource`` adapter is exercised in
``test_dart_financial_statement_data_source_adapter.py``.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from src.adapters.dart_financial_data_source import FakeFinancialStatementDataSource
from src.domain.financial_statement import ConsolidatedType, FinancialStatementInfo, FiscalQuarter


def test_fake_financial_statement_data_source_returns_requested_tickers_only() -> None:
    source = FakeFinancialStatementDataSource()

    statements = asyncio.run(
        source.get_quarterly_statements(["005930", "999999"], 2025, FiscalQuarter.ANNUAL)
    )

    assert len(statements) == 1
    assert all(isinstance(s, FinancialStatementInfo) for s in statements)
    assert statements[0].ticker == "005930"
    assert statements[0].fiscal_year == 2025
    assert statements[0].fiscal_quarter == FiscalQuarter.ANNUAL
    assert statements[0].consolidated_type == ConsolidatedType.CFS
    assert statements[0].revenue == Decimal(300_000_000_000_000)


def test_fake_financial_statement_data_source_returns_nothing_for_unknown_tickers() -> None:
    source = FakeFinancialStatementDataSource()

    statements = asyncio.run(
        source.get_quarterly_statements(["069500"], 2025, FiscalQuarter.Q1)
    )

    assert statements == []


def test_fake_financial_statement_data_source_is_deterministic() -> None:
    source = FakeFinancialStatementDataSource()

    first = asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.H1))
    second = asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.H1))

    assert first == second


def test_fake_financial_statement_data_source_all_six_line_items_populated() -> None:
    source = FakeFinancialStatementDataSource()

    statements = asyncio.run(
        source.get_quarterly_statements(["000660"], 2025, FiscalQuarter.Q3)
    )

    statement = statements[0]
    assert statement.revenue is not None
    assert statement.operating_income is not None
    assert statement.net_income is not None
    assert statement.total_assets is not None
    assert statement.total_liabilities is not None
    assert statement.total_equity is not None
    assert statement.rcept_no
