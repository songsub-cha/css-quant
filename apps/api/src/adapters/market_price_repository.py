"""SQLAlchemy implementation of the market price repository port (SoT C1/C3 — adapters).

Implements ``src.domain.market_price.MarketPriceRepository`` structurally,
importing only ``domain`` per the layer contract ("adapters는 domain만
import") — same structure as ``SqlAlchemyAssetRepository``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.market_price import DailyPriceInfo, MarketPrice, PriceBar


class SqlAlchemyMarketPriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, asset_id: UUID, bar: DailyPriceInfo) -> MarketPrice | None:
        result = await self._session.execute(
            select(MarketPrice).where(
                MarketPrice.asset_id == asset_id, MarketPrice.date == bar.date
            )
        )
        return result.scalar_one_or_none()

    def _apply(self, row: MarketPrice, bar: DailyPriceInfo) -> None:
        row.open = bar.open
        row.high = bar.high
        row.low = bar.low
        row.close = bar.close
        row.adjusted_close = bar.adjusted_close
        row.volume = bar.volume
        row.trading_value = bar.trading_value
        row.market_cap = bar.market_cap
        row.halted = bar.halted

    async def upsert(self, *, asset_id: UUID, bar: DailyPriceInfo) -> MarketPrice:
        existing = await self._get(asset_id, bar)
        if existing is not None:
            self._apply(existing, bar)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        row = MarketPrice(
            asset_id=asset_id,
            date=bar.date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            adjusted_close=bar.adjusted_close,
            volume=bar.volume,
            trading_value=bar.trading_value,
            market_cap=bar.market_cap,
            halted=bar.halted,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another sync run inserted this (asset_id, date) bar
            # between the lookup above and this commit — the PK
            # (asset_id, date) is the real guard. Fall back to updating
            # that row, mirroring SqlAlchemyAssetRepository.upsert_active.
            #
            # A FK violation (asset_id no longer in assets) lands here too;
            # the retry lookup below then finds nothing and re-raises the
            # original error instead of silently swallowing it.
            await self._session.rollback()
            existing = await self._get(asset_id, bar)
            if existing is None:
                raise
            self._apply(existing, bar)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(row)
        return row

    async def get_market_caps(self, *, trade_date: date) -> dict[UUID, Decimal | None]:
        result = await self._session.execute(
            select(MarketPrice.asset_id, MarketPrice.market_cap).where(
                MarketPrice.date == trade_date
            )
        )
        return dict(result.tuples().all())

    async def get_avg_trading_value(self, *, as_of_date: date, window: int) -> dict[UUID, Decimal]:
        # Bound to as_of_date first (look-ahead prevention), then pick the
        # `window` most recent *actual* trading days within that bound —
        # a single query (CTE + IN), not one round trip per asset.
        recent_dates = (
            select(MarketPrice.date)
            .where(MarketPrice.date <= as_of_date)
            .distinct()
            .order_by(MarketPrice.date.desc())
            .limit(window)
            .cte("recent_trading_dates")
        )
        result = await self._session.execute(
            select(MarketPrice.asset_id, func.avg(MarketPrice.trading_value))
            .where(MarketPrice.date.in_(select(recent_dates.c.date)))
            .group_by(MarketPrice.asset_id)
        )
        return dict(result.tuples().all())

    async def get_price_history(
        self, *, asset_ids: Sequence[UUID], as_of_date: date, window: int
    ) -> dict[UUID, list[PriceBar]]:
        if not asset_ids:
            return {}

        # Market-wide recent trading dates (not per-asset), same CTE
        # rationale as get_avg_trading_value: bound to as_of_date first
        # (look-ahead prevention), then pick the `window` most recent
        # *actual* trading days within that bound.
        recent_dates = (
            select(MarketPrice.date)
            .where(MarketPrice.date <= as_of_date)
            .distinct()
            .order_by(MarketPrice.date.desc())
            .limit(window)
            .cte("recent_trading_dates")
        )
        result = await self._session.execute(
            select(MarketPrice)
            .where(
                MarketPrice.asset_id.in_(asset_ids),
                MarketPrice.date.in_(select(recent_dates.c.date)),
            )
            .order_by(MarketPrice.asset_id, MarketPrice.date.asc())
        )
        by_asset: dict[UUID, list[PriceBar]] = {}
        for row in result.scalars().all():
            by_asset.setdefault(row.asset_id, []).append(
                PriceBar(
                    date=row.date,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    adjusted_close=row.adjusted_close,
                    volume=row.volume,
                    trading_value=row.trading_value,
                    halted=row.halted,
                )
            )
        return by_asset
