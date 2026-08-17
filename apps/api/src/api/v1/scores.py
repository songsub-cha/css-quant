"""GET /api/v1/scores — AI score ranking read endpoint (SoT A5.2/A6.1, thin router).

``router -> service -> adapter/domain`` (SoT B2, same shape as
``api/v1/auth.py``): all sorting/joining happens in
``src.services.scores.list_ranked_scores``; this module only wires the
request, requires auth (owner-only data, same principle as every other
protected endpoint), and shapes the response.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from src.api.deps import get_asset_repository, get_asset_score_repository, get_current_user
from src.domain.ai_score import AssetScore, AssetScoreRepository
from src.domain.asset import ASSET_ID_PREFIX, Asset, AssetRepository
from src.domain.ids import format_prefixed_id
from src.domain.market_regime import RegimeStatus
from src.domain.user import User
from src.services.scores import list_ranked_scores

router = APIRouter(prefix="/api/v1/scores", tags=["scores"])


class ScoreRankingItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str
    ticker: str
    name: str
    regime: RegimeStatus

    total_score: Decimal
    momentum_score: Decimal
    quality_score: Decimal
    value_score: Decimal
    liquidity_score: Decimal
    risk_score: Decimal

    summary: str | None
    positive_reasons: list[str] | None
    risk_reasons: list[str] | None

    @classmethod
    def from_pair(cls, score: AssetScore, asset: Asset) -> ScoreRankingItem:
        return cls(
            asset_id=format_prefixed_id(ASSET_ID_PREFIX, score.asset_id),
            ticker=asset.ticker,
            name=asset.name,
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
        )


class ScoreRankingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    score_date: date | None
    scores: list[ScoreRankingItem]


@router.get("")
async def list_scores(
    score_repo: Annotated[AssetScoreRepository, Depends(get_asset_score_repository)],
    asset_repo: Annotated[AssetRepository, Depends(get_asset_repository)],
    _current_user: Annotated[User, Depends(get_current_user)],
    score_date: Annotated[date | None, Query()] = None,
) -> ScoreRankingResponse:
    resolved_date, pairs = await list_ranked_scores(
        score_repo, asset_repo, score_date=score_date
    )
    return ScoreRankingResponse(
        score_date=resolved_date,
        scores=[ScoreRankingItem.from_pair(score, asset) for score, asset in pairs],
    )
