"""Pure normalization + weighted-sum math (SoT A6.1 stages 3/4 — engine).

Deterministic, DB-free math only (SoT A2 원칙 7 — "숫자는 결정론적 코드"): this
module takes an already-fetched day's ``asset_factors`` rows and a regime's
``FactorWeights`` and returns each asset's normalized factor scores and
weighted ``total_score``. All I/O — fetching ``asset_factors``/
``market_regimes`` rows and upserting the result into ``ai_scores`` — is
``src.workers.score_calculation``'s job; this module only imports
``src.domain``, per the layer contract (``src.engine`` may depend on
domain/adapters, never services/api/workers).

**Normalization** (SoT A6.1 3): each of the 15 constituent indicators is
independently winsorized (top/bottom 1% clipped, linear interpolation for
the clip bounds — matching ``numpy.percentile``'s default ``linear``
method) across that day's universe, then converted to a 0~100 mean-rank
percentile: ``(값보다 작은 개수 + 동값 개수 × 0.5) / 전체 × 100``. A missing
(``None``) indicator value is *not* winsorized/ranked — it is directly
assigned the neutral percentile (50), per SoT's "결측 50 중립" rule.
``lower_is_better`` indicators (SoT does not label these explicitly; this
module's own design decision, per issue #62's plan) are then reversed
(``100 - percentile``) so that every indicator's post-reversal percentile
means the same thing: higher is always better.

A **factor score** is the plain mean of its constituent indicators'
post-reversal percentiles. Averaging two neutral-50 stand-ins for a
partially-missing factor is intentional (SoT 원칙 8 — the *missing-factor
hold* rule below is what protects the pipeline from treating an
all-missing factor as a genuine neutral judgement, not a special-cased
score value).

A **missing factor** is one whose constituent indicators are *all* ``None``
in the raw (pre-normalization) input. If an asset has
``missing_factor_hold_threshold`` or more missing factors, it is marked
``on_hold`` and its ``total_score`` is not computed — ``src.workers.
score_calculation`` writes no ``ai_scores`` row for it (SoT A6.1 3).

The **weighted sum** (SoT A6.1 4) is ``total = Σ weights[factor] ×
factor_score`` for the single ``FactorWeights`` instance the caller passes
in — already regime-selected (``RegimeWeightProfile.for_regime``) by the
worker, so this module never imports ``RegimeStatus`` itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from src.domain.ai_score import FactorWeights
from src.domain.asset_factor import AssetFactor

_NEUTRAL_PERCENTILE = Decimal(50)
_WINSORIZE_LOWER_Q = Decimal(1)
_WINSORIZE_UPPER_Q = Decimal(99)
_SCORE_QUANT = Decimal("0.01")

# indicator name -> True if a higher raw value is better, False if lower is better.
_INDICATOR_HIGHER_IS_BETTER: dict[str, bool] = {
    "momentum_3m": True,
    "momentum_6m": True,
    "dist_52w_high": True,
    "ma20_deviation": True,
    "roe": True,
    "op_margin": True,
    "revenue_growth_yoy": True,
    "debt_ratio": False,
    "per": False,
    "pbr": False,
    "avg_trading_value_20d": True,
    "volume_cv": False,
    # Closer to 0 (less drawdown) is better — mdd_60d is always <= 0 (SoT
    # A6.1 2 / src.engine.factor_calculation._mdd_60d's docstring).
    "mdd_60d": True,
    "volatility_60d": False,
    "gap_frequency_60d": False,
}

_FACTOR_INDICATORS: dict[str, tuple[str, ...]] = {
    "momentum": ("momentum_3m", "momentum_6m", "dist_52w_high", "ma20_deviation"),
    "quality": ("roe", "op_margin", "revenue_growth_yoy", "debt_ratio"),
    "value": ("per", "pbr"),
    "liquidity": ("avg_trading_value_20d", "volume_cv"),
    "risk": ("volatility_60d", "mdd_60d", "gap_frequency_60d"),
}


@dataclass(frozen=True)
class AssetScoreResult:
    asset_id: UUID
    momentum_score: Decimal
    quality_score: Decimal
    value_score: Decimal
    liquidity_score: Decimal
    risk_score: Decimal
    on_hold: bool
    total_score: Decimal | None


def _interpolated_percentile(sorted_values: Sequence[Decimal], q: Decimal) -> Decimal:
    """Linear-interpolation percentile matching ``numpy.percentile``'s default method.

    ``sorted_values`` must already be ascending.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    rank = q / Decimal(100) * Decimal(n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    frac = rank - Decimal(lower_idx)
    return sorted_values[lower_idx] + (sorted_values[upper_idx] - sorted_values[lower_idx]) * frac


def _mean_rank_percentile(value: Decimal, values: Sequence[Decimal]) -> Decimal:
    n = len(values)
    less = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (Decimal(less) + Decimal(equal) * Decimal("0.5")) / Decimal(n) * Decimal(100)


def _winsorized_percentile_ranks(values: Sequence[Decimal | None]) -> list[Decimal]:
    """Winsorize (top/bottom 1% clip) the present values, then mean-rank percentile
    (0~100) each one — missing values are assigned the neutral percentile directly,
    without participating in the clip-bound computation or the ranking.
    """
    present = [v for v in values if v is not None]
    if not present:
        return [_NEUTRAL_PERCENTILE for _ in values]

    sorted_present = sorted(present)
    lower_bound = _interpolated_percentile(sorted_present, _WINSORIZE_LOWER_Q)
    upper_bound = _interpolated_percentile(sorted_present, _WINSORIZE_UPPER_Q)
    clipped = [min(max(v, lower_bound), upper_bound) for v in present]

    ranks: list[Decimal] = []
    clipped_iter = iter(clipped)
    for v in values:
        if v is None:
            ranks.append(_NEUTRAL_PERCENTILE)
        else:
            clipped_value = next(clipped_iter)
            ranks.append(_mean_rank_percentile(clipped_value, clipped))
    return ranks


def normalize_and_score(
    factors: Sequence[AssetFactor],
    *,
    weights: FactorWeights,
    missing_factor_hold_threshold: int,
) -> list[AssetScoreResult]:
    """Normalize every indicator across ``factors`` (one day's universe), then compute
    each asset's factor scores and (unless on-hold) ``total_score``.

    ``factors`` must all share the same ``factor_date`` — the caller
    (``src.workers.score_calculation.calculate_scores``) enforces this by
    fetching via ``AssetFactorRepository.get_by_factor_date``.
    """
    if not factors:
        return []

    raw_values: dict[str, list[Decimal | None]] = {
        indicator: [getattr(factor, indicator) for factor in factors]
        for indicator in _INDICATOR_HIGHER_IS_BETTER
    }

    indicator_percentiles: dict[str, list[Decimal]] = {}
    for indicator, higher_is_better in _INDICATOR_HIGHER_IS_BETTER.items():
        ranks = _winsorized_percentile_ranks(raw_values[indicator])
        indicator_percentiles[indicator] = (
            ranks if higher_is_better else [Decimal(100) - rank for rank in ranks]
        )

    results: list[AssetScoreResult] = []
    for i, factor_row in enumerate(factors):
        factor_scores: dict[str, Decimal] = {}
        missing_factor_count = 0
        for factor_name, indicators in _FACTOR_INDICATORS.items():
            raw = [raw_values[indicator][i] for indicator in indicators]
            if all(v is None for v in raw):
                missing_factor_count += 1
            percentiles = [indicator_percentiles[indicator][i] for indicator in indicators]
            mean_percentile = sum(percentiles, start=Decimal(0)) / Decimal(len(percentiles))
            factor_scores[factor_name] = mean_percentile.quantize(_SCORE_QUANT)

        on_hold = missing_factor_count >= missing_factor_hold_threshold
        total_score = None
        if not on_hold:
            total_score = sum(
                (getattr(weights, name) * score for name, score in factor_scores.items()),
                start=Decimal(0),
            ).quantize(_SCORE_QUANT)

        results.append(
            AssetScoreResult(
                asset_id=factor_row.asset_id,
                momentum_score=factor_scores["momentum"],
                quality_score=factor_scores["quality"],
                value_score=factor_scores["value"],
                liquidity_score=factor_scores["liquidity"],
                risk_score=factor_scores["risk"],
                on_hold=on_hold,
                total_score=total_score,
            )
        )
    return results
