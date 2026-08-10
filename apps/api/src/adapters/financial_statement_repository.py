"""SQLAlchemy implementation of the financial statement repository port (SoT C1/A6.1 — adapters).

Implements ``src.domain.financial_statement.FinancialStatementRepository``
structurally, importing only ``domain`` per the layer contract — same
lookup-then-insert + ``IntegrityError`` TOCTOU structure as
``SqlAlchemyIndexPriceRepository``, keyed on
``(asset_id, fiscal_year, fiscal_quarter)``.

Unlike the price repositories, an existing row here is not just refreshed
with the latest bar — it also represents a 정정공시 (corrected disclosure)
carrying a new ``rcept_no``/``disclosed_at``, so ``_apply`` replaces those
alongside the six line items rather than assuming they never change once set.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.financial_statement import (
    DisclosedStatement,
    FinancialStatement,
    FinancialStatementInfo,
)


class SqlAlchemyFinancialStatementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(
        self, asset_id: UUID, statement: FinancialStatementInfo
    ) -> FinancialStatement | None:
        result = await self._session.execute(
            select(FinancialStatement).where(
                FinancialStatement.asset_id == asset_id,
                FinancialStatement.fiscal_year == statement.fiscal_year,
                FinancialStatement.fiscal_quarter == statement.fiscal_quarter,
            )
        )
        return result.scalar_one_or_none()

    def _apply(self, row: FinancialStatement, statement: FinancialStatementInfo) -> None:
        row.consolidated_type = statement.consolidated_type
        row.revenue = statement.revenue
        row.operating_income = statement.operating_income
        row.net_income = statement.net_income
        row.total_assets = statement.total_assets
        row.total_liabilities = statement.total_liabilities
        row.total_equity = statement.total_equity
        row.disclosed_at = statement.disclosed_at
        row.rcept_no = statement.rcept_no

    async def upsert(
        self, *, asset_id: UUID, statement: FinancialStatementInfo
    ) -> FinancialStatement:
        existing = await self._get(asset_id, statement)
        if existing is not None:
            self._apply(existing, statement)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        row = FinancialStatement(
            asset_id=asset_id,
            fiscal_year=statement.fiscal_year,
            fiscal_quarter=statement.fiscal_quarter,
            consolidated_type=statement.consolidated_type,
            revenue=statement.revenue,
            operating_income=statement.operating_income,
            net_income=statement.net_income,
            total_assets=statement.total_assets,
            total_liabilities=statement.total_liabilities,
            total_equity=statement.total_equity,
            disclosed_at=statement.disclosed_at,
            rcept_no=statement.rcept_no,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another sync run inserted this
            # (asset_id, fiscal_year, fiscal_quarter) row between the lookup
            # above and this commit — same recovery as
            # SqlAlchemyIndexPriceRepository.upsert.
            await self._session.rollback()
            existing = await self._get(asset_id, statement)
            if existing is None:
                raise
            self._apply(existing, statement)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(row)
        return row

    async def get_statement_history(
        self, *, asset_ids: Sequence[UUID], as_of_date: date
    ) -> dict[UUID, list[DisclosedStatement]]:
        if not asset_ids:
            return {}

        result = await self._session.execute(
            select(FinancialStatement).where(
                FinancialStatement.asset_id.in_(asset_ids),
                FinancialStatement.disclosed_at <= as_of_date,
            )
        )
        by_asset: dict[UUID, list[DisclosedStatement]] = {}
        for row in result.scalars().all():
            by_asset.setdefault(row.asset_id, []).append(
                DisclosedStatement(
                    fiscal_year=row.fiscal_year,
                    fiscal_quarter=row.fiscal_quarter,
                    revenue=row.revenue,
                    operating_income=row.operating_income,
                    net_income=row.net_income,
                    total_assets=row.total_assets,
                    total_liabilities=row.total_liabilities,
                    total_equity=row.total_equity,
                    disclosed_at=row.disclosed_at,
                )
            )
        return by_asset
