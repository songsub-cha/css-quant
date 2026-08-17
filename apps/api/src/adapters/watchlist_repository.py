"""SQLAlchemy implementation of the watchlist repository port (SoT A5.2/C3 — adapters).

Implements ``src.domain.watchlist.WatchlistItemRepository`` structurally,
importing only ``domain`` per the layer contract — same lookup-then-insert +
``IntegrityError`` TOCTOU structure as ``SqlAlchemyAssetScoreRepository``,
keyed on ``(user_id, asset_id)`` (the table's named unique constraint)
rather than the primary key.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.watchlist import WatchlistItem, WatchlistItemInfo, WatchlistKind


class SqlAlchemyWatchlistItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, *, user_id: UUID, asset_id: UUID) -> WatchlistItem | None:
        result = await self._session.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.asset_id == asset_id,
            )
        )
        return result.scalar_one_or_none()

    def _apply(self, row: WatchlistItem, item: WatchlistItemInfo) -> None:
        row.kind = item.kind
        row.note = item.note

    async def upsert(self, *, item: WatchlistItemInfo) -> WatchlistItem:
        existing = await self._get(user_id=item.user_id, asset_id=item.asset_id)
        if existing is not None:
            self._apply(existing, item)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        row = WatchlistItem(
            user_id=item.user_id,
            asset_id=item.asset_id,
            kind=item.kind,
            note=item.note,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another request inserted this (user_id, asset_id) row
            # between the lookup above and this commit — same recovery as
            # SqlAlchemyAssetScoreRepository.upsert.
            await self._session.rollback()
            existing = await self._get(user_id=item.user_id, asset_id=item.asset_id)
            if existing is None:
                raise
            self._apply(existing, item)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(row)
        return row

    async def remove(self, *, user_id: UUID, asset_id: UUID) -> None:
        existing = await self._get(user_id=user_id, asset_id=asset_id)
        if existing is None:
            return
        await self._session.delete(existing)
        await self._session.commit()

    async def list_by_user(
        self, *, user_id: UUID, kind: WatchlistKind | None = None
    ) -> list[WatchlistItem]:
        stmt = select(WatchlistItem).where(WatchlistItem.user_id == user_id)
        if kind is not None:
            stmt = stmt.where(WatchlistItem.kind == kind)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
