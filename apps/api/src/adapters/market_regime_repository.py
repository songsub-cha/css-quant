"""SQLAlchemy implementation of the market regime repository port (SoT A6.2/A6.3 — adapters).

Implements ``src.domain.market_regime.MarketRegimeRepository`` structurally,
importing only ``domain`` per the layer contract — same
upsert/TOCTOU-recovery shape as ``SqlAlchemyIndexPriceRepository``, keyed on
``regime_date`` alone instead of a composite key.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.market_regime import MarketRegime, MarketRegimeInfo


class SqlAlchemyMarketRegimeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, regime_date: date) -> MarketRegime | None:
        result = await self._session.execute(
            select(MarketRegime).where(MarketRegime.regime_date == regime_date)
        )
        return result.scalar_one_or_none()

    def _apply(self, row: MarketRegime, regime: MarketRegimeInfo) -> None:
        row.regime = regime.regime
        row.kospi_close = regime.kospi_close
        row.kospi_ma200 = regime.kospi_ma200
        row.vkospi = regime.vkospi
        row.kospi_volatility_20d = regime.kospi_volatility_20d
        row.market_shock = regime.market_shock
        row.signals = regime.signals

    async def upsert(self, *, regime: MarketRegimeInfo) -> MarketRegime:
        existing = await self._get(regime.regime_date)
        if existing is not None:
            self._apply(existing, regime)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        row = MarketRegime(
            regime_date=regime.regime_date,
            regime=regime.regime,
            kospi_close=regime.kospi_close,
            kospi_ma200=regime.kospi_ma200,
            vkospi=regime.vkospi,
            kospi_volatility_20d=regime.kospi_volatility_20d,
            market_shock=regime.market_shock,
            signals=regime.signals,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another detection run inserted this regime_date's row
            # between the lookup above and this commit — same recovery as
            # SqlAlchemyIndexPriceRepository.upsert.
            await self._session.rollback()
            existing = await self._get(regime.regime_date)
            if existing is None:
                raise
            self._apply(existing, regime)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(row)
        return row

    async def get_recent(self, *, before_date: date, limit: int) -> list[MarketRegime]:
        result = await self._session.execute(
            select(MarketRegime)
            .where(MarketRegime.regime_date < before_date)
            .order_by(MarketRegime.regime_date.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_date(self, *, regime_date: date) -> MarketRegime | None:
        result = await self._session.execute(
            select(MarketRegime).where(MarketRegime.regime_date == regime_date)
        )
        return result.scalar_one_or_none()
