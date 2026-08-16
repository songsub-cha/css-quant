"""Unit tests for ``src.engine.score_calculation`` (SoT A6.1 stages 3/4).

Pure DB-free math — no fakes, no fixtures, just already-built ``AssetFactor``
rows (constructed directly, no session) and asserted outputs. Mirrors
``test_factor_calculation_engine.py``'s style: where a formula is
nontrivial, the expected value is computed by hand using the same formula
the implementation documents (mean-rank percentile, linear-interpolation
percentile), rather than a black-box magic number.

The winsorizing/mean-rank helpers (``_interpolated_percentile``/
``_mean_rank_percentile``/``_winsorized_percentile_ranks``) are tested
directly (imported by their underscored names) because winsorizing's effect
is otherwise unobservable through ``normalize_and_score``'s public output:
mean-rank percentile only depends on relative order, so clipping a single
outlier never changes its own rank unless the clip causes two previously-
distinct raw values to collapse to the identical clipped bound (a tie) —
see ``test_winsorizing_ties_extreme_outliers_at_the_clip_bound`` below for
that scenario.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.domain.ai_score import FactorWeights
from src.domain.asset_factor import AssetFactor
from src.engine.score_calculation import (
    _interpolated_percentile,
    _mean_rank_percentile,
    _winsorized_percentile_ranks,
    normalize_and_score,
)

_NORMAL_WEIGHTS = FactorWeights(
    momentum=Decimal("0.35"),
    quality=Decimal("0.25"),
    value=Decimal("0.20"),
    liquidity=Decimal("0.10"),
    risk=Decimal("0.10"),
)
_DEFENSIVE_WEIGHTS = FactorWeights(
    momentum=Decimal("0.15"),
    quality=Decimal("0.35"),
    value=Decimal("0.20"),
    liquidity=Decimal("0.10"),
    risk=Decimal("0.20"),
)


def _factor_row(
    *,
    asset_id: UUID | None = None,
    momentum_3m: Decimal | None = Decimal(0),
    momentum_6m: Decimal | None = Decimal(0),
    dist_52w_high: Decimal | None = Decimal(0),
    ma20_deviation: Decimal | None = Decimal(0),
    roe: Decimal | None = Decimal(0),
    op_margin: Decimal | None = Decimal(0),
    revenue_growth_yoy: Decimal | None = Decimal(0),
    debt_ratio: Decimal | None = Decimal(0),
    per: Decimal | None = Decimal(10),
    pbr: Decimal | None = Decimal(1),
    avg_trading_value_20d: Decimal | None = Decimal(1_000_000_000),
    volume_cv: Decimal | None = Decimal("0.2"),
    volatility_60d: Decimal | None = Decimal("0.1"),
    mdd_60d: Decimal | None = Decimal("-0.05"),
    gap_frequency_60d: Decimal | None = Decimal("0.01"),
) -> AssetFactor:
    return AssetFactor(
        asset_id=asset_id if asset_id is not None else uuid4(),
        factor_date=date(2026, 8, 16),
        momentum_3m=momentum_3m,
        momentum_6m=momentum_6m,
        dist_52w_high=dist_52w_high,
        ma20_deviation=ma20_deviation,
        roe=roe,
        op_margin=op_margin,
        revenue_growth_yoy=revenue_growth_yoy,
        debt_ratio=debt_ratio,
        per=per,
        pbr=pbr,
        avg_trading_value_20d=avg_trading_value_20d,
        volume_cv=volume_cv,
        volatility_60d=volatility_60d,
        mdd_60d=mdd_60d,
        gap_frequency_60d=gap_frequency_60d,
        market_cap=Decimal(0),
        is_managed=False,
        is_alert=False,
        financial_data_as_of=None,
    )


def test_interpolated_percentile_matches_numpy_linear_method() -> None:
    sorted_values = [Decimal(10), Decimal(20), Decimal(30), Decimal(40), Decimal(50)]

    assert _interpolated_percentile(sorted_values, Decimal(50)) == Decimal(30)
    assert _interpolated_percentile(sorted_values, Decimal(25)) == Decimal(20)
    assert _interpolated_percentile(sorted_values, Decimal(10)) == Decimal(14)


def test_mean_rank_percentile_averages_tied_ranks() -> None:
    values = [Decimal(10), Decimal(20), Decimal(20), Decimal(30)]

    assert _mean_rank_percentile(Decimal(10), values) == Decimal("12.5")
    assert _mean_rank_percentile(Decimal(20), values) == Decimal(50)
    assert _mean_rank_percentile(Decimal(30), values) == Decimal("87.5")


def test_missing_value_gets_neutral_50_without_affecting_present_ranks() -> None:
    ranks = _winsorized_percentile_ranks([Decimal(0), Decimal(100), None])

    assert ranks == [Decimal(25), Decimal(75), Decimal(50)]


def test_winsorizing_ties_extreme_outliers_at_the_clip_bound() -> None:
    """101 points so the 1st-percentile clip bound (linear interpolation) lands
    exactly on the second-smallest raw value, dragging *both* of the two lowest
    (distinct) raw values to that same clipped value — a tie that plain
    (unwinsorized) rank ordering would never produce, since -1000 < -999 are
    themselves distinct and would otherwise rank 0.5/101*100 and 1.5/101*100
    respectively.
    """
    values = (
        [Decimal(-1000), Decimal(-999)]
        + [Decimal(k) for k in range(1, 98)]
        + [Decimal(99), Decimal(99)]
    )
    assert len(values) == 101

    ranks = _winsorized_percentile_ranks(values)

    expected_tied_rank = (Decimal(0) + Decimal(2) * Decimal("0.5")) / Decimal(101) * Decimal(100)
    assert ranks[0] == expected_tied_rank
    assert ranks[1] == expected_tied_rank


def test_partial_missing_indicator_within_factor_uses_neutral_50() -> None:
    """One asset's ``momentum_3m`` is missing while its other three momentum
    indicators tie with every other asset's (all identical -> rank 50 each).
    The two assets with a real ``momentum_3m`` rank 25/75 *between
    themselves*, unaffected by the missing asset; the missing asset's own
    momentum score is exactly 50 (neutral substitution averaged with three
    50s stays 50).
    """
    missing = _factor_row(momentum_3m=None)
    low = _factor_row(momentum_3m=Decimal(10))
    high = _factor_row(momentum_3m=Decimal(20))

    results = normalize_and_score(
        [missing, low, high], weights=_NORMAL_WEIGHTS, missing_factor_hold_threshold=3
    )
    by_id = {r.asset_id: r for r in results}

    assert by_id[missing.asset_id].momentum_score == Decimal("50.00")
    assert by_id[low.asset_id].momentum_score == Decimal("43.75")
    assert by_id[high.asset_id].momentum_score == Decimal("56.25")


def test_lower_is_better_indicator_reverses_direction() -> None:
    """PER (Value factor, lower-is-better): the cheap (low-PER) asset must score
    *higher* than the expensive (high-PER) one. PBR is held identical between
    both assets so it ties at neutral 50 and only PER drives the difference.
    """
    cheap = _factor_row(per=Decimal(5))
    expensive = _factor_row(per=Decimal(20))

    results = normalize_and_score(
        [cheap, expensive], weights=_NORMAL_WEIGHTS, missing_factor_hold_threshold=3
    )
    by_id = {r.asset_id: r for r in results}

    assert by_id[cheap.asset_id].value_score == Decimal("62.50")
    assert by_id[expensive.asset_id].value_score == Decimal("37.50")


def test_mdd_closer_to_zero_scores_higher() -> None:
    """``mdd_60d`` is always <= 0 (SoT A6.1 2) but is higher-is-better: less
    drawdown (closer to 0) must score higher, not lower."""
    shallow_drawdown = _factor_row(mdd_60d=Decimal("-0.05"))
    deep_drawdown = _factor_row(mdd_60d=Decimal("-0.40"))

    results = normalize_and_score(
        [shallow_drawdown, deep_drawdown],
        weights=_NORMAL_WEIGHTS,
        missing_factor_hold_threshold=3,
    )
    by_id = {r.asset_id: r for r in results}

    assert by_id[shallow_drawdown.asset_id].risk_score > by_id[deep_drawdown.asset_id].risk_score


def test_missing_factor_count_at_threshold_marks_asset_on_hold() -> None:
    """Momentum, Quality, and Value are *entirely* missing (3 of 5 factors) —
    at the default threshold of 3, the asset is put on hold and gets no
    ``total_score``."""
    held = _factor_row(
        momentum_3m=None,
        momentum_6m=None,
        dist_52w_high=None,
        ma20_deviation=None,
        roe=None,
        op_margin=None,
        revenue_growth_yoy=None,
        debt_ratio=None,
        per=None,
        pbr=None,
    )
    ok = _factor_row()

    results = normalize_and_score(
        [held, ok], weights=_NORMAL_WEIGHTS, missing_factor_hold_threshold=3
    )
    by_id = {r.asset_id: r for r in results}

    assert by_id[held.asset_id].on_hold is True
    assert by_id[held.asset_id].total_score is None
    assert by_id[ok.asset_id].on_hold is False
    assert by_id[ok.asset_id].total_score is not None


def test_missing_factor_count_below_threshold_does_not_hold() -> None:
    """Only Momentum and Quality are entirely missing (2 of 5 factors) — below
    the default threshold of 3, so the asset is scored normally."""
    partial = _factor_row(
        momentum_3m=None,
        momentum_6m=None,
        dist_52w_high=None,
        ma20_deviation=None,
        roe=None,
        op_margin=None,
        revenue_growth_yoy=None,
        debt_ratio=None,
    )
    ok = _factor_row()

    results = normalize_and_score(
        [partial, ok], weights=_NORMAL_WEIGHTS, missing_factor_hold_threshold=3
    )
    by_id = {r.asset_id: r for r in results}

    assert by_id[partial.asset_id].on_hold is False
    assert by_id[partial.asset_id].total_score is not None


def test_regime_weights_change_total_score_for_the_same_factor_snapshot() -> None:
    """Asset X has strong Momentum but weak Quality; Asset Y is the mirror image.
    Value/Liquidity/Risk are identical between them (tie at neutral 50).
    NORMAL weights Momentum highest (0.35) — favoring X; DEFENSIVE weights
    Quality highest (0.35) — favoring Y. The *same* two factor snapshots must
    therefore produce different ``total_score`` under each profile.
    """
    asset_x = _factor_row(
        momentum_3m=Decimal(10),
        momentum_6m=Decimal(20),
        dist_52w_high=Decimal("-0.05"),
        ma20_deviation=Decimal("0.05"),
        roe=Decimal(5),
        op_margin=Decimal(5),
        revenue_growth_yoy=Decimal(5),
        debt_ratio=Decimal(10),  # lower-is-better: high value = bad quality
    )
    asset_y = _factor_row(
        momentum_3m=Decimal(5),
        momentum_6m=Decimal(10),
        dist_52w_high=Decimal("-0.10"),
        ma20_deviation=Decimal("0.01"),
        roe=Decimal(10),
        op_margin=Decimal(10),
        revenue_growth_yoy=Decimal(10),
        debt_ratio=Decimal(5),  # lower-is-better: low value = good quality
    )

    normal_results = {
        r.asset_id: r
        for r in normalize_and_score(
            [asset_x, asset_y], weights=_NORMAL_WEIGHTS, missing_factor_hold_threshold=3
        )
    }
    defensive_results = {
        r.asset_id: r
        for r in normalize_and_score(
            [asset_x, asset_y], weights=_DEFENSIVE_WEIGHTS, missing_factor_hold_threshold=3
        )
    }

    assert normal_results[asset_x.asset_id].momentum_score == Decimal("75.00")
    assert normal_results[asset_x.asset_id].quality_score == Decimal("25.00")
    assert normal_results[asset_x.asset_id].total_score == Decimal("52.50")
    assert defensive_results[asset_x.asset_id].total_score == Decimal("45.00")
    assert (
        normal_results[asset_x.asset_id].total_score
        != defensive_results[asset_x.asset_id].total_score
    )


def test_factor_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        FactorWeights(
            momentum=Decimal("0.5"),
            quality=Decimal("0.5"),
            value=Decimal("0.5"),
            liquidity=Decimal(0),
            risk=Decimal(0),
        )
