"""SQLAlchemy implementation of the strategy repository port (SoT A5.3/C3 — adapters).

Implements ``src.domain.strategy.StrategyRepository`` structurally, importing
only ``domain`` per the layer contract. ``get_by_id``/``list_by_user`` both
filter ``deleted_at IS NULL`` (SoT B4.10 soft delete) and scope by
``user_id`` in the query itself — an IDOR guard that never fetches another
owner's row into memory to compare against, matching
``SqlAlchemyWatchlistItemRepository``'s scoping approach.

``update``/``soft_delete`` operate on an already-fetched, session-attached
``Strategy`` — the service layer mutates fields on it directly, and these
methods just persist the pending changes (SQLAlchemy's unit-of-work already
tracks the mutation; ``commit`` is what flushes it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.strategy import Strategy, StrategyInfo, StrategyStatus


class SqlAlchemyStrategyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, info: StrategyInfo) -> Strategy:
        row = Strategy(
            user_id=info.user_id,
            name=info.name,
            description=info.description,
            status=StrategyStatus.DRAFT,
            execution_mode=info.execution_mode,
            config=info.config,
            version=1,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get_by_id(self, *, user_id: UUID, strategy_id: UUID) -> Strategy | None:
        result = await self._session.execute(
            select(Strategy).where(
                Strategy.id == strategy_id,
                Strategy.user_id == user_id,
                Strategy.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, *, user_id: UUID, status: StrategyStatus | None = None
    ) -> list[Strategy]:
        stmt = select(Strategy).where(
            Strategy.user_id == user_id, Strategy.deleted_at.is_(None)
        )
        if status is not None:
            stmt = stmt.where(Strategy.status == status)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, strategy: Strategy) -> Strategy:
        await self._session.commit()
        await self._session.refresh(strategy)
        return strategy

    async def soft_delete(self, strategy: Strategy) -> None:
        strategy.deleted_at = datetime.now(UTC)
        await self._session.commit()
