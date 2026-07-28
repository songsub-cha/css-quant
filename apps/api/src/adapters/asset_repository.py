"""SQLAlchemy implementation of the asset repository port (SoT C1/C3 — adapters).

Implements ``src.domain.asset.AssetRepository`` structurally, importing only
``domain`` per the layer contract ("adapters는 domain만 import") — same
structure as ``SqlAlchemyUserRepository``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.asset import Asset, AssetType, Exchange, Market


class SqlAlchemyAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_by_ticker(self, ticker: str, market: Market) -> Asset | None:
        result = await self._session.execute(
            select(Asset).where(
                Asset.ticker == ticker, Asset.market == market, Asset.is_active.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def upsert_active(
        self,
        *,
        ticker: str,
        name: str,
        market: Market,
        asset_type: AssetType,
        exchange: Exchange,
    ) -> Asset:
        existing = await self.get_active_by_ticker(ticker, market)
        if existing is not None:
            existing.name = name
            existing.asset_type = asset_type
            existing.exchange = exchange
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        asset = Asset(
            ticker=ticker, name=name, market=market, asset_type=asset_type, exchange=exchange
        )
        self._session.add(asset)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another sync run inserted an active row for this
            # (ticker, market) between the lookup above and this commit —
            # the partial unique index (uq_assets_ticker_market_active) is
            # the real guard. Fall back to updating that row instead of
            # raising, mirroring services.auth.bootstrap_owner's TOCTOU
            # handling.
            await self._session.rollback()
            existing = await self.get_active_by_ticker(ticker, market)
            if existing is None:
                raise
            existing.name = name
            existing.asset_type = asset_type
            existing.exchange = exchange
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(asset)
        return asset
