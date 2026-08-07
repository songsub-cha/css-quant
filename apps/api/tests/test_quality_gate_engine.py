"""Unit tests for ``judge_quality_gate`` (SoT A6.4).

Pure DB-free function — no fakes, no ``asyncio.run`` needed, same shape as
``test_market_regime_engine.py``/``test_universe_filter_engine.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from src.domain.market_price import PriceCheckBar
from src.domain.quality_gate import QualityCheckName, QualityCheckResult, QualityGateThresholds
from src.engine.quality_gate import judge_quality_gate

_GATE_DATE = date(2026, 8, 7)
_THRESHOLDS = QualityGateThresholds(
    coverage_min_pct=Decimal("0.98"), max_price_move_pct=Decimal("0.30")
)


def _bar(close: int = 100, high: int | None = None, low: int | None = None) -> PriceCheckBar:
    return PriceCheckBar(
        close=Decimal(close),
        high=Decimal(high if high is not None else close),
        low=Decimal(low if low is not None else close),
    )


def _find(checks: list[QualityCheckResult], name: QualityCheckName) -> QualityCheckResult:
    return next(c for c in checks if c.name == name)


def test_all_checks_pass_yields_gate_passed() -> None:
    asset_ids = {uuid4() for _ in range(3)}
    today_bars = {asset_id: _bar() for asset_id in asset_ids}

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids=asset_ids,
        today_bars=today_bars,
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    assert result.passed is True
    assert all(check.passed for check in result.checks)


def test_freshness_fails_when_no_bars_today() -> None:
    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids=set(),
        today_bars={},
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    freshness = _find(result.checks, QualityCheckName.FRESHNESS)
    assert freshness.passed is False
    assert result.passed is False


def test_coverage_fails_below_threshold() -> None:
    asset_ids = [uuid4() for _ in range(100)]
    covered = asset_ids[:97]  # 97/100 = 97% < 98%
    today_bars = {asset_id: _bar() for asset_id in covered}

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids=set(asset_ids),
        today_bars=today_bars,
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    coverage = _find(result.checks, QualityCheckName.COVERAGE)
    assert coverage.passed is False
    assert coverage.details["coverage_pct"] == 0.97
    assert result.passed is False


def test_coverage_passes_at_exactly_the_threshold() -> None:
    asset_ids = [uuid4() for _ in range(100)]
    covered = asset_ids[:98]  # 98/100 = 98% == threshold
    today_bars = {asset_id: _bar() for asset_id in covered}

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids=set(asset_ids),
        today_bars=today_bars,
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    coverage = _find(result.checks, QualityCheckName.COVERAGE)
    assert coverage.passed is True


def test_coverage_fails_closed_on_empty_universe() -> None:
    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids=set(),
        today_bars={},
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    coverage = _find(result.checks, QualityCheckName.COVERAGE)
    assert coverage.passed is False
    assert coverage.details["coverage_pct"] is None


def test_integrity_passes_with_zero_violations() -> None:
    asset_ids = {uuid4() for _ in range(3)}
    today_bars = {asset_id: _bar() for asset_id in asset_ids}

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids=asset_ids,
        today_bars=today_bars,
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    integrity = _find(result.checks, QualityCheckName.INTEGRITY)
    assert integrity.passed is True
    assert integrity.details["violation_count"] == 0


def test_integrity_fails_on_non_positive_close() -> None:
    bad_asset = uuid4()
    good_asset = uuid4()
    today_bars = {bad_asset: _bar(close=0), good_asset: _bar()}

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids={bad_asset, good_asset},
        today_bars=today_bars,
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    integrity = _find(result.checks, QualityCheckName.INTEGRITY)
    assert integrity.passed is False
    assert integrity.details["violation_count"] == 1
    assert integrity.details["reason_counts"] == {"close_non_positive": 1}
    assert integrity.details["sample_violating_asset_ids"] == [str(bad_asset)]
    assert result.passed is False


def test_integrity_fails_on_high_below_low() -> None:
    bad_asset = uuid4()
    today_bars = {bad_asset: _bar(close=100, high=90, low=110)}

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids={bad_asset},
        today_bars=today_bars,
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    integrity = _find(result.checks, QualityCheckName.INTEGRITY)
    assert integrity.passed is False
    assert integrity.details["reason_counts"] == {"high_below_low": 1}
    assert result.passed is False


def test_integrity_fails_on_price_move_exceeding_threshold() -> None:
    bad_asset = uuid4()
    today_bars = {bad_asset: _bar(close=140)}
    prev_closes: dict[UUID, Decimal] = {bad_asset: Decimal(100)}  # +40% > 30% threshold

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids={bad_asset},
        today_bars=today_bars,
        prev_closes=prev_closes,
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    integrity = _find(result.checks, QualityCheckName.INTEGRITY)
    assert integrity.passed is False
    assert integrity.details["reason_counts"] == {"price_move_exceeds_threshold": 1}
    assert result.passed is False


def test_integrity_skips_price_move_check_for_asset_with_no_prior_close() -> None:
    """A new listing (or a prior-session collection gap) has no ``prev_closes`` entry —
    the ±30% leg must skip silently rather than raise/violate, and the other
    legs (close/high-low) must still run unaffected."""
    new_listing = uuid4()
    # would be a huge "move" if compared against any baseline
    today_bars = {new_listing: _bar(close=100_000)}

    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids={new_listing},
        today_bars=today_bars,
        prev_closes={},
        market_regime_exists=True,
        thresholds=_THRESHOLDS,
    )

    integrity = _find(result.checks, QualityCheckName.INTEGRITY)
    assert integrity.passed is True
    assert integrity.details["violation_count"] == 0
    assert result.passed is True


def test_indicator_fails_when_market_regime_missing() -> None:
    asset_id = uuid4()
    result = judge_quality_gate(
        gate_date=_GATE_DATE,
        universe_asset_ids={asset_id},
        today_bars={asset_id: _bar()},
        prev_closes={},
        market_regime_exists=False,
        thresholds=_THRESHOLDS,
    )

    indicator = _find(result.checks, QualityCheckName.INDICATOR)
    assert indicator.passed is False
    assert result.passed is False
