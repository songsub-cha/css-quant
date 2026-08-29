"""SQLAlchemy implementation of the AI score repository port (SoT A6.1/C3 — adapters).

Implements ``src.domain.ai_score.AssetScoreRepository`` structurally,
importing only ``domain`` per the layer contract — same lookup-then-insert +
``IntegrityError`` TOCTOU structure as ``SqlAlchemyAssetFactorRepository``,
keyed on ``(asset_id, score_date)`` with identity already embedded in the
DTO (``AssetScoreInfo``).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ai_score import AssetScore, AssetScoreInfo


class SqlAlchemyAssetScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, score: AssetScoreInfo) -> AssetScore | None:
        result = await self._session.execute(
            select(AssetScore).where(
                AssetScore.asset_id == score.asset_id,
                AssetScore.score_date == score.score_date,
            )
        )
        return result.scalar_one_or_none()

    def _apply(self, row: AssetScore, score: AssetScoreInfo) -> None:
        row.regime = score.regime
        row.total_score = score.total_score
        row.momentum_score = score.momentum_score
        row.quality_score = score.quality_score
        row.value_score = score.value_score
        row.liquidity_score = score.liquidity_score
        row.risk_score = score.risk_score
        row.summary = score.summary
        row.positive_reasons = score.positive_reasons
        row.risk_reasons = score.risk_reasons
        row.llm_model = score.llm_model
        row.llm_generated_at = score.llm_generated_at

    async def upsert(self, *, score: AssetScoreInfo) -> AssetScore:
        existing = await self._get(score)
        if existing is not None:
            self._apply(existing, score)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing

        row = AssetScore(
            asset_id=score.asset_id,
            score_date=score.score_date,
            regime=score.regime,
            total_score=score.total_score,
            momentum_score=score.momentum_score,
            quality_score=score.quality_score,
            value_score=score.value_score,
            liquidity_score=score.liquidity_score,
            risk_score=score.risk_score,
            summary=score.summary,
            positive_reasons=score.positive_reasons,
            risk_reasons=score.risk_reasons,
            llm_model=score.llm_model,
            llm_generated_at=score.llm_generated_at,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # TOCTOU: another run inserted this (asset_id, score_date) row
            # between the lookup above and this commit — same recovery as
            # SqlAlchemyAssetFactorRepository.upsert.
            await self._session.rollback()
            existing = await self._get(score)
            if existing is None:
                raise
            self._apply(existing, score)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        await self._session.refresh(row)
        return row

    async def get_by_date(self, *, score_date: date) -> list[AssetScore]:
        result = await self._session.execute(
            select(AssetScore).where(AssetScore.score_date == score_date)
        )
        return list(result.scalars().all())

    async def get_latest_score_date(self) -> date | None:
        result = await self._session.execute(select(func.max(AssetScore.score_date)))
        return result.scalar_one_or_none()
