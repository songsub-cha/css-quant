"""DART quarterly financial statement schema + data source port (SoT C1/A6.1/A6.7.2 — domain).

``FinancialStatementDataSource``/``FinancialStatementRepository`` follow the
same fetch-then-upsert split as ``PriceDataSource``/``MarketPriceRepository``,
but ``get_quarterly_statements`` takes an explicit ``tickers`` argument —
unlike pykrx's bulk OHLCV endpoints, DART's ``fnlttSinglAcntAll`` has no
all-companies-at-once call, so the concrete adapter (``DartFinancialStatementDataSource``,
``src/adapters/dart_financial_data_source.py``) fetches one company per call.

This module only adds raw-collection plumbing (SoT A8 Phase 2). Two things
are deliberately deferred to a later Phase 3 issue:

- Derived factors (ROE/영업이익률/매출성장YoY/부채비율/PER/PBR/EV/EBITDA) and
  TTM (trailing-twelve-month) summation — this table stores as-reported
  quarterly/annual line items only.
- EV/EBITDA's additional line items (감가상각비/무형자산상각비/총차입금/
  현금성자산). DART's ``account_nm`` is free text that varies by company for
  anything below the six top-level BS/IS totals stored here, so a reliable
  matching rule for those needs its own design — a later issue's scope.

Half-year (H1) and Q3 income-statement figures (``revenue``/
``operating_income``/``net_income``) are DART's own **cumulative**
year-to-date values, not that quarter's isolated delta — stored as-reported;
quarterly differencing is the factor-calculation issue's concern (SoT
A6.7.2 look-ahead prevention needs ``disclosed_at`` alongside the raw
figures, which this module provides).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class ConsolidatedType(StrEnum):
    CFS = "CFS"
    OFS = "OFS"


class FiscalQuarter(StrEnum):
    """DART reporting period. No ``Q4`` member — DART has no standalone Q4
    report; the fourth quarter is only ever covered by the annual report
    (``ANNUAL``, DART ``reprt_code`` 11011). The ``FiscalQuarter -> reprt_code``
    mapping itself is fixed in ``src/adapters/dart_financial_data_source.py``.
    """

    Q1 = "Q1"
    H1 = "H1"
    Q3 = "Q3"
    ANNUAL = "ANNUAL"


class FinancialStatementInfo(BaseModel):
    """External-facing representation of one company's quarterly/annual statement.

    ``ticker``-keyed, like ``DailyPriceInfo`` — ``src.services.financial_statement_sync``
    maps ``ticker`` to ``asset_id`` via ``AssetRepository`` before upserting.
    Each of the six line items is independently nullable: DART's response for
    a given company/period may only populate some of them (see the module
    docstring on ``account_nm`` matching risk).
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    fiscal_quarter: FiscalQuarter
    consolidated_type: ConsolidatedType
    revenue: Decimal | None
    operating_income: Decimal | None
    net_income: Decimal | None
    total_assets: Decimal | None
    total_liabilities: Decimal | None
    total_equity: Decimal | None
    disclosed_at: date
    rcept_no: str


class DisclosedStatement(BaseModel):
    """One already-persisted, already-disclosed quarterly/annual statement (SoT A6.1/A6.7.2).

    ``FinancialStatementRepository.get_statement_history``'s read-only output
    shape — unlike ``FinancialStatementInfo``, this carries no
    ``ticker``/``consolidated_type``/``rcept_no``: the caller
    (``src.engine.factor_calculation.isolate_quarterly_income``) only needs
    the six line items plus the period they cover and when they were
    disclosed. ``consolidated_type`` is omitted because
    ``financial_statements``' primary key is ``(asset_id, fiscal_year,
    fiscal_quarter)`` alone (issue #51 already resolved CFS/OFS at
    collection time) — at most one row exists per period, so there is
    nothing to disambiguate here.
    """

    model_config = ConfigDict(frozen=True)

    fiscal_year: int
    fiscal_quarter: FiscalQuarter
    revenue: Decimal | None
    operating_income: Decimal | None
    net_income: Decimal | None
    total_assets: Decimal | None
    total_liabilities: Decimal | None
    total_equity: Decimal | None
    disclosed_at: date


class FinancialStatementDataSource(Protocol):
    """Port for DART quarterly financial statement collection.

    ``DartFinancialStatementDataSource`` (``src/adapters/dart_financial_data_source.py``)
    is the real implementation, selected via ``Settings.data_source`` the same
    way ``PykrxDataSource``/``PykrxPriceDataSource`` are (SoT B3). Unlike
    those bulk-call adapters, DART's ``fnlttSinglAcntAll`` endpoint is
    per-company, so this port takes an explicit ``tickers`` list rather than
    fetching the whole market in one call.
    """

    async def get_quarterly_statements(
        self, tickers: list[str], fiscal_year: int, fiscal_quarter: FiscalQuarter
    ) -> list[FinancialStatementInfo]: ...


class FinancialStatementRepository(Protocol):
    """Port ``src.services.financial_statement_sync`` depends on.

    Same role as ``MarketPriceRepository``. Identity is
    ``(asset_id, fiscal_year, fiscal_quarter)``, matching
    ``FinancialStatement``'s composite primary key.
    """

    async def upsert(
        self, *, asset_id: UUID, statement: FinancialStatementInfo
    ) -> FinancialStatement:
        """Update the ``(asset_id, statement.fiscal_year, statement.fiscal_quarter)`` row if
        one exists (including replacing ``rcept_no``/``disclosed_at``/line items on a
        정정공시 restatement), else insert a new one.
        """
        ...

    async def get_statement_history(
        self, *, asset_ids: Sequence[UUID], as_of_date: date
    ) -> dict[UUID, list[DisclosedStatement]]:
        """Every requested asset's disclosed statements with ``disclosed_at <= as_of_date``.

        Structural SoT A6.7.2 look-ahead bound: a statement disclosed after
        ``as_of_date`` can never enter the returned dict, so a caller
        (``src.engine.factor_calculation``'s quarterly-differencing/TTM
        math) cannot accidentally use financial data the market did not yet
        have on ``as_of_date`` — same bounding rationale as
        ``MarketPriceRepository.get_avg_trading_value``'s ``date <=
        as_of_date``. No ordering is guaranteed within each asset's list;
        the caller re-sorts by an explicit ``FiscalQuarter`` rank (a
        ``StrEnum`` member's alphabetical order is not its chronological
        order). An ``asset_id`` with no disclosed statements in range is
        absent from the returned dict — callers must treat a missing key as
        "no data", not zero.
        """
        ...


class FinancialStatement(Base):
    """DART quarterly/annual financial statement row (SoT C1/A6.1/A6.7.2 — financial_statements).

    Identity is ``(asset_id, fiscal_year, fiscal_quarter)`` — one row per
    company per reporting period, replaced in place on a 정정공시
    (restatement) rather than accumulating a new row (see
    ``FinancialStatementRepository.upsert`` docstring). ``rcept_no`` is
    additionally UNIQUE: it identifies the specific DART disclosure document
    this row's figures came from.

    See the module docstring for what this table deliberately excludes
    (derived factors, TTM summation, EV/EBITDA's extra line items) and the
    半期/3분기 손익 누적치 caveat.
    """

    __tablename__ = "financial_statements"

    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_quarter: Mapped[FiscalQuarter] = mapped_column(
        SAEnum(
            FiscalQuarter, name="fiscal_quarter", values_callable=lambda e: [x.value for x in e]
        ),
        primary_key=True,
    )
    consolidated_type: Mapped[ConsolidatedType] = mapped_column(
        SAEnum(
            ConsolidatedType,
            name="consolidated_type",
            values_callable=lambda e: [x.value for x in e],
        )
    )
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    total_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    total_equity: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    disclosed_at: Mapped[date] = mapped_column(Date)
    rcept_no: Mapped[str] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
