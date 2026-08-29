"""Score calculation orchestration (SoT A6.1 stages 3/4/6 — workers).

Same layer-contract rationale as ``src.workers.factor_calculation``: an
orchestrator that calls ``src.engine.score_calculation``'s pure functions
cannot live in ``src.services`` (its ``forbidden_modules`` includes
``src.engine``, ``apps/api/pyproject.toml``), so ``src.workers`` is the
legal home.

Registering ``calculate_scores`` as an actual Arq cron job and recording its
runs in ``job_runs`` is issue #39's scope — this module only provides the
callable pipeline: fetch the day's ``asset_factors`` universe and regime ->
normalize + weighted-sum every included asset -> upsert non-held assets into
``ai_scores``.
"""

from __future__ import annotations

from datetime import date

from src.domain.ai_score import (
    AssetScore,
    AssetScoreInfo,
    AssetScoreRepository,
    MissingRegimeError,
    RegimeWeightProfile,
)
from src.domain.asset_factor import AssetFactorRepository
from src.domain.market_regime import MarketRegimeRepository
from src.engine.score_calculation import normalize_and_score


async def calculate_scores(
    asset_factor_repo: AssetFactorRepository,
    market_regime_repo: MarketRegimeRepository,
    asset_score_repo: AssetScoreRepository,
    *,
    as_of_date: date,
    weights: RegimeWeightProfile,
    missing_factor_hold_threshold: int,
) -> list[AssetScore]:
    """Fetch ``as_of_date``'s factor universe + regime, normalize/score, and upsert.

    Raises ``MissingRegimeError`` if ``as_of_date`` has no ``market_regimes``
    row yet (fail-closed, SoT A2 원칙 8) — the weighted-sum step (SoT A6.1 4)
    cannot select a weight profile without knowing which regime was in
    effect, and the regime must be persisted alongside the score for
    reproducibility.

    Assets ``src.engine.score_calculation.normalize_and_score`` marks
    ``on_hold`` get no ``ai_scores`` row (SoT A6.1 3) — same "excluded means
    no row" convention as ``src.workers.factor_calculation``.
    """
    factors = await asset_factor_repo.get_by_factor_date(factor_date=as_of_date)
    if not factors:
        return []

    regime = await market_regime_repo.get_by_date(regime_date=as_of_date)
    if regime is None:
        raise MissingRegimeError(f"no market_regimes row for {as_of_date}")

    factor_weights = weights.for_regime(regime.regime)
    results = normalize_and_score(
        factors,
        weights=factor_weights,
        missing_factor_hold_threshold=missing_factor_hold_threshold,
    )

    scores: list[AssetScore] = []
    for result in results:
        if result.on_hold or result.total_score is None:
            continue
        score_info = AssetScoreInfo(
            asset_id=result.asset_id,
            score_date=as_of_date,
            regime=regime.regime,
            total_score=result.total_score,
            momentum_score=result.momentum_score,
            quality_score=result.quality_score,
            value_score=result.value_score,
            liquidity_score=result.liquidity_score,
            risk_score=result.risk_score,
        )
        scores.append(await asset_score_repo.upsert(score=score_info))

    return scores
