"""SQLAlchemy implementation of the index price repository port (SoT A6.2/A6.3 — adapters).

Implements ``src.domain.index_price.IndexPriceRepository`` structurally,
importing only ``domain`` per the layer contract — same structure/TOCTOU
handling as ``SqlAlchemyMarketPriceRepository``, keyed on
``(index_code, date)`` instead of ``(asset_id, date)``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.index_price import IndexPrice, IndexPriceInfo


class SqlAlchemyIndexPriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, bar: IndexPriceInfo) -> IndexPrice | None:
        result = await self._session.execute(
            select(IndexPrice).where(
                IndexPrice.index_code == bar.index_code, IndexPrice.date == bar.date
            )
        )
        return result.scalar_one_or_none()

    def _apply(self, row: IndexPrice, bar: IndexPriceInfo) -> None:
        row.open = bar.open
        row.high = bar.high
        row.low = bar.low
        row.close = bar.close
        row.volume = bar.volume
        row.trading_value = bar.trading_value

    async def upsert(self, *, bar: IndexPriceInfo) -> IndexPrice:
        existing = await self._get(bar)
        if existing is not None:
            self._apply(existing, bar)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        row = IndexPrice(
            index_code=bar.index_code,
            date=bar.date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            trading_value=bar.trading_value,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another sync run inserted this (index_code, date) bar
            # between the lookup above and this commit — same recovery as
            # SqlAlchemyMarketPriceRepository.upsert.
            await self._session.rollback()
            existing = await self._get(bar)
            if existing is None:
                raise
            self._apply(existing, bar)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(row)
        return row
