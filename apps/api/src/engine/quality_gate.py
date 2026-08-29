"""Pure data quality gate judgement (SoT A6.4/A2 원칙 8 — engine).

Deterministic, DB-free math only (SoT A2 원칙 7 — "숫자는 결정론적 코드"): every
check here takes already-fetched values and returns a verdict, the same
DB-free shape ``src.engine.market_regime``/``src.engine.universe_filter``
use. All I/O — fetching the candidate universe, today's/yesterday's
``market_prices`` rows, and today's ``market_regimes`` row, then recording
the result into ``job_runs.stats`` — is ``src.workers.quality_gate``'s job;
this module only imports ``src.domain``, per the layer contract
(``src.engine`` may depend on domain/adapters, never services/api/workers).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from src.domain.market_price import PriceCheckBar
from src.domain.quality_gate import (
    QualityCheckName,
    QualityCheckResult,
    QualityGateResult,
    QualityGateThresholds,
)

# Cap on how many violating asset IDs the integrity check's ``details``
# carries — job_runs.stats must not grow unbounded on a bad day (the count
# is already the pass/fail signal; the sample is diagnostic only).
_INTEGRITY_SAMPLE_LIMIT = 20


def _check_freshness(today_bars: dict[UUID, PriceCheckBar]) -> QualityCheckResult:
    """Passes iff at least one ``market_prices`` row exists for today.

    A non-empty ``today_bars`` is itself the evidence that "latest price
    date == today's trading day" — the caller (``evaluate_quality_gate``)
    only ever fetches rows dated exactly ``as_of_date``, so a stale-data day
    (yesterday's rows still the latest) fetches nothing here.
    """
    passed = bool(today_bars)
    return QualityCheckResult(
        name=QualityCheckName.FRESHNESS,
        passed=passed,
        details={"today_bar_count": len(today_bars)},
    )


def _check_coverage(
    universe_asset_ids: set[UUID],
    today_bars: dict[UUID, PriceCheckBar],
    thresholds: QualityGateThresholds,
) -> QualityCheckResult:
    """Passes iff >= ``thresholds.coverage_min_pct`` of the candidate pool has today's bar.

    ``universe_asset_ids`` is the filter-*before* candidate pool (active KR
    STOCK assets, not ``evaluate_universe``'s filtered result) — see
    ``src.workers.quality_gate``'s docstring for why using the filtered
    result as the denominator would hide market-cap/trading-value collection
    gaps as a fail-open. An empty universe fails closed (SoT A2 원칙 8)
    rather than divide by zero / vacuously pass.
    """
    universe_count = len(universe_asset_ids)
    covered_count = len(universe_asset_ids & today_bars.keys())
    if universe_count == 0:
        return QualityCheckResult(
            name=QualityCheckName.COVERAGE,
            passed=False,
            details={
                "universe_count": 0,
                "covered_count": 0,
                "coverage_pct": None,
                "min_required_pct": float(thresholds.coverage_min_pct),
            },
        )

    coverage_pct = Decimal(covered_count) / Decimal(universe_count)
    passed = coverage_pct >= thresholds.coverage_min_pct
    return QualityCheckResult(
        name=QualityCheckName.COVERAGE,
        passed=passed,
        details={
            "universe_count": universe_count,
            "covered_count": covered_count,
            "coverage_pct": float(coverage_pct),
            "min_required_pct": float(thresholds.coverage_min_pct),
        },
    )


def _check_integrity(
    today_bars: dict[UUID, PriceCheckBar],
    prev_closes: dict[UUID, Decimal],
    thresholds: QualityGateThresholds,
) -> QualityCheckResult:
    """Passes iff zero assets violate close<=0, high<low, or a ±move-threshold breach.

    "=0 violations", not a tolerance ratio — any single bad bar fails the
    whole check (SoT A6.4). The ±move leg only runs for assets present in
    ``prev_closes``; an asset with no prior-session bar (new listing, or a
    prior-session collection gap) simply skips that one leg, mirroring
    ``detect_market_shock``'s treatment of a missing VKOSPI bar.
    """
    reason_counts: dict[str, int] = {}
    violating_asset_ids: list[UUID] = []

    for asset_id, bar in today_bars.items():
        reasons: list[str] = []
        if bar.close <= 0:
            reasons.append("close_non_positive")
        if bar.high < bar.low:
            reasons.append("high_below_low")
        prev_close = prev_closes.get(asset_id)
        if prev_close is not None and prev_close != 0:
            change_pct = abs(bar.close / prev_close - 1)
            if change_pct > thresholds.max_price_move_pct:
                reasons.append("price_move_exceeds_threshold")

        if reasons:
            violating_asset_ids.append(asset_id)
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    passed = not violating_asset_ids
    return QualityCheckResult(
        name=QualityCheckName.INTEGRITY,
        passed=passed,
        details={
            "violation_count": len(violating_asset_ids),
            "reason_counts": reason_counts,
            "sample_violating_asset_ids": [
                str(asset_id) for asset_id in violating_asset_ids[:_INTEGRITY_SAMPLE_LIMIT]
            ],
        },
    )


def _check_indicator(market_regime_exists: bool) -> QualityCheckResult:
    """Passes iff today's ``market_regimes`` row exists (SoT A6.4's "KOSPI·200MA 계산 가능").

    Reused rather than recomputed: ``detect_market_regime`` (#54) already
    raises ``InsufficientPriceHistoryError`` and skips the upsert when the
    200-day KOSPI history is too short, so today's row existing is itself
    the proof the indicator was computable.
    """
    return QualityCheckResult(
        name=QualityCheckName.INDICATOR,
        passed=market_regime_exists,
        details={"market_regime_exists": market_regime_exists},
    )


def judge_quality_gate(
    *,
    gate_date: date,
    universe_asset_ids: set[UUID],
    today_bars: dict[UUID, PriceCheckBar],
    prev_closes: dict[UUID, Decimal],
    market_regime_exists: bool,
    thresholds: QualityGateThresholds,
) -> QualityGateResult:
    """Judge all four SoT A6.4 checks independently and combine into one verdict.

    Each check is evaluated regardless of whether an earlier one failed (no
    short-circuiting) — the caller needs every check's ``details`` recorded
    in ``job_runs.stats`` even on a failing day, not just the first failure.
    """
    checks = [
        _check_freshness(today_bars),
        _check_coverage(universe_asset_ids, today_bars, thresholds),
        _check_integrity(today_bars, prev_closes, thresholds),
        _check_indicator(market_regime_exists),
    ]
    passed = all(check.passed for check in checks)
    return QualityGateResult(gate_date=gate_date, passed=passed, checks=checks)
