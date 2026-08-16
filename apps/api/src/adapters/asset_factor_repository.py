"""SQLAlchemy implementation of the asset factor repository port (SoT A6.1/C3 — adapters).

Implements ``src.domain.asset_factor.AssetFactorRepository`` structurally,
importing only ``domain`` per the layer contract — same lookup-then-insert +
``IntegrityError`` TOCTOU structure as ``SqlAlchemyIndexPriceRepository``,
keyed on ``(asset_id, factor_date)`` with identity already embedded in the
DTO (``AssetFactorInfo``).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.asset_factor import AssetFactor, AssetFactorInfo


class SqlAlchemyAssetFactorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, factor: AssetFactorInfo) -> AssetFactor | None:
        result = await self._session.execute(
            select(AssetFactor).where(
                AssetFactor.asset_id == factor.asset_id,
                AssetFactor.factor_date == factor.factor_date,
            )
        )
        return result.scalar_one_or_none()

    def _apply(self, row: AssetFactor, factor: AssetFactorInfo) -> None:
        row.momentum_3m = factor.momentum_3m
        row.momentum_6m = factor.momentum_6m
        row.dist_52w_high = factor.dist_52w_high
        row.ma20_deviation = factor.ma20_deviation
        row.roe = factor.roe
        row.op_margin = factor.op_margin
        row.revenue_growth_yoy = factor.revenue_growth_yoy
        row.debt_ratio = factor.debt_ratio
        row.per = factor.per
        row.pbr = factor.pbr
        row.avg_trading_value_20d = factor.avg_trading_value_20d
        row.volume_cv = factor.volume_cv
        row.volatility_60d = factor.volatility_60d
        row.mdd_60d = factor.mdd_60d
        row.gap_frequency_60d = factor.gap_frequency_60d
        row.market_cap = factor.market_cap
        row.is_managed = factor.is_managed
        row.is_alert = factor.is_alert
        row.financial_data_as_of = factor.financial_data_as_of

    async def upsert(self, *, factor: AssetFactorInfo) -> AssetFactor:
        existing = await self._get(factor)
        if existing is not None:
            self._apply(existing, factor)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        row = AssetFactor(
            asset_id=factor.asset_id,
            factor_date=factor.factor_date,
            momentum_3m=factor.momentum_3m,
            momentum_6m=factor.momentum_6m,
            dist_52w_high=factor.dist_52w_high,
            ma20_deviation=factor.ma20_deviation,
            roe=factor.roe,
            op_margin=factor.op_margin,
            revenue_growth_yoy=factor.revenue_growth_yoy,
            debt_ratio=factor.debt_ratio,
            per=factor.per,
            pbr=factor.pbr,
            avg_trading_value_20d=factor.avg_trading_value_20d,
            volume_cv=factor.volume_cv,
            volatility_60d=factor.volatility_60d,
            mdd_60d=factor.mdd_60d,
            gap_frequency_60d=factor.gap_frequency_60d,
            market_cap=factor.market_cap,
            is_managed=factor.is_managed,
            is_alert=factor.is_alert,
            financial_data_as_of=factor.financial_data_as_of,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another run inserted this (asset_id, factor_date) row
            # between the lookup above and this commit — same recovery as
            # SqlAlchemyIndexPriceRepository.upsert. A FK violation
            # (asset_id no longer in assets) lands here too; the retry
            # lookup below then finds nothing and re-raises the original
            # error instead of silently swallowing it.
            await self._session.rollback()
            existing = await self._get(factor)
            if existing is None:
                raise
            self._apply(existing, factor)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(row)
        return row

    async def get_by_factor_date(self, *, factor_date: date) -> list[AssetFactor]:
        result = await self._session.execute(
            select(AssetFactor).where(AssetFactor.factor_date == factor_date)
        )
        return list(result.scalars().all())
