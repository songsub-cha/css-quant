"""Unit tests for ``src.engine.market_regime`` (SoT A6.2/A6.3).

Pure DB-free math — no fakes, no fixtures, just Decimal inputs and asserted
outputs.
"""

from __future__ import annotations

import statistics
from decimal import Decimal

import pytest

from src.domain.market_regime import InsufficientPriceHistoryError, RegimeStatus
from src.engine.market_regime import (
    calculate_ma200,
    calculate_volatility_20d,
    detect_market_shock,
    judge_regime,
)


def _closes(values: list[int]) -> list[Decimal]:
    return [Decimal(v) for v in values]


class TestCalculateMa200:
    def test_averages_the_trailing_200_closes(self) -> None:
        closes = _closes([100] * 199 + [300])  # trailing 200 = 199x100 + 1x300

        result = calculate_ma200(closes)

        assert result == Decimal(100) * 199 / 200 + Decimal(300) / 200

    def test_extra_leading_history_is_ignored(self) -> None:
        closes = _closes([9_999] * 50 + [100] * 200)

        result = calculate_ma200(closes)

        assert result == Decimal(100)

    def test_raises_when_fewer_than_200_closes(self) -> None:
        closes = _closes([100] * 199)

        with pytest.raises(InsufficientPriceHistoryError):
            calculate_ma200(closes)


class TestCalculateVolatility20d:
    def test_raises_when_fewer_than_21_closes(self) -> None:
        closes = _closes([100] * 20)

        with pytest.raises(InsufficientPriceHistoryError):
            calculate_volatility_20d(closes)

    def test_matches_stdev_of_trailing_20_daily_returns(self) -> None:
        raw = [2_600, 2_620, 2_590, 2_650, 2_630] * 4 + [2_665]  # 21 closes
        closes = _closes(raw)
        expected_returns = [
            Decimal(raw[i]) / Decimal(raw[i - 1]) - 1 for i in range(1, len(raw))
        ]
        expected = statistics.stdev(expected_returns)

        result = calculate_volatility_20d(closes)

        assert result == expected

    def test_result_is_on_a_daily_scale_not_annualized(self) -> None:
        """A ~1%/day-swing series should stay a small fraction, not blow up by sqrt(252)."""
        raw = [10_000, 10_100, 9_950, 10_080, 9_970] * 4 + [10_050]
        closes = _closes(raw)

        result = calculate_volatility_20d(closes)

        # Annualizing (x sqrt(252) ~= 15.87) would push this well past 1.5%/25;
        # the raw daily-scale figure must stay under the SoT's 1.5% NORMAL threshold.
        assert result < Decimal("0.015")
        assert result * Decimal("15") < Decimal(1)

    def test_extra_leading_history_is_ignored(self) -> None:
        noisy_prefix = _closes([1, 500, 2, 800, 3])
        raw = [2_600, 2_620, 2_590, 2_650, 2_630] * 4 + [2_665]
        closes = noisy_prefix + _closes(raw)
        expected_returns = [
            Decimal(raw[i]) / Decimal(raw[i - 1]) - 1 for i in range(1, len(raw))
        ]
        expected = statistics.stdev(expected_returns)

        result = calculate_volatility_20d(closes)

        assert result == expected


class TestDetectMarketShock:
    def test_kospi_leg_triggers_on_3pct_single_day_drop(self) -> None:
        shock, signals = detect_market_shock(
            kospi_prev_close=Decimal(1_000),
            kospi_close=Decimal(960),  # -4%
            vkospi=None,
            vkospi_history_20d=[],
        )

        assert shock is True
        assert signals["kospi_shock"] is True
        assert signals["vkospi_shock"] is None

    def test_kospi_leg_does_not_trigger_on_a_2pct_drop(self) -> None:
        shock, signals = detect_market_shock(
            kospi_prev_close=Decimal(1_000),
            kospi_close=Decimal(980),  # -2%
            vkospi=None,
            vkospi_history_20d=[],
        )

        assert shock is False
        assert signals["kospi_shock"] is False

    def test_vkospi_leg_triggers_when_above_1_5x_trailing_average(self) -> None:
        shock, signals = detect_market_shock(
            kospi_prev_close=Decimal(1_000),
            kospi_close=Decimal(1_000),
            vkospi=Decimal(31),
            vkospi_history_20d=[Decimal(20)] * 20,  # avg=20, threshold=30
        )

        assert shock is True
        assert signals["kospi_shock"] is False
        assert signals["vkospi_shock"] is True
        assert signals["vkospi_avg_20d"] == 20.0
        assert signals["vkospi_threshold"] == 30.0

    def test_vkospi_leg_missing_data_is_skipped_not_destructive(self) -> None:
        shock, signals = detect_market_shock(
            kospi_prev_close=Decimal(1_000),
            kospi_close=Decimal(1_000),
            vkospi=Decimal(40),
            vkospi_history_20d=[],  # collection gap
        )

        assert shock is False
        assert signals["vkospi_shock"] is None
        assert signals["vkospi_avg_20d"] is None

    def test_neither_leg_triggers(self) -> None:
        shock, signals = detect_market_shock(
            kospi_prev_close=Decimal(1_000),
            kospi_close=Decimal(1_000),
            vkospi=Decimal(18),
            vkospi_history_20d=[Decimal(20)] * 20,
        )

        assert shock is False


class TestJudgeRegime:
    def test_cold_start_is_always_defensive(self) -> None:
        regime, signals = judge_regime(
            kospi_close=Decimal(3_000),
            kospi_ma200=Decimal(2_500),  # raw condition satisfied
            vkospi=Decimal(15),
            kospi_volatility_20d=Decimal("0.005"),
            previous_regime=None,
            previous_raw_normal=[],
        )

        assert regime == RegimeStatus.DEFENSIVE
        assert signals["raw_normal"] is True

    def test_normal_to_defensive_is_immediate(self) -> None:
        regime, _signals = judge_regime(
            kospi_close=Decimal(2_400),
            kospi_ma200=Decimal(2_500),  # below MA -> raw condition violated
            vkospi=Decimal(15),
            kospi_volatility_20d=Decimal("0.005"),
            previous_regime=RegimeStatus.NORMAL,
            previous_raw_normal=[True],
        )

        assert regime == RegimeStatus.DEFENSIVE

    def test_normal_stays_normal_when_condition_holds(self) -> None:
        regime, _signals = judge_regime(
            kospi_close=Decimal(3_000),
            kospi_ma200=Decimal(2_500),
            vkospi=Decimal(15),
            kospi_volatility_20d=Decimal("0.005"),
            previous_regime=RegimeStatus.NORMAL,
            previous_raw_normal=[True],
        )

        assert regime == RegimeStatus.NORMAL

    def test_defensive_to_normal_requires_3_consecutive_raw_satisfied_days(self) -> None:
        regime, _signals = judge_regime(
            kospi_close=Decimal(3_000),
            kospi_ma200=Decimal(2_500),  # today raw satisfied
            vkospi=Decimal(15),
            kospi_volatility_20d=Decimal("0.005"),
            previous_regime=RegimeStatus.DEFENSIVE,
            previous_raw_normal=[True, True],  # prior 2 days also satisfied
        )

        assert regime == RegimeStatus.NORMAL

    def test_defensive_stays_when_only_2_of_3_days_satisfied(self) -> None:
        regime, _signals = judge_regime(
            kospi_close=Decimal(3_000),
            kospi_ma200=Decimal(2_500),  # today raw satisfied
            vkospi=Decimal(15),
            kospi_volatility_20d=Decimal("0.005"),
            previous_regime=RegimeStatus.DEFENSIVE,
            previous_raw_normal=[True, False],  # one prior day failed
        )

        assert regime == RegimeStatus.DEFENSIVE

    def test_defensive_stays_when_only_1_prior_day_available(self) -> None:
        regime, _signals = judge_regime(
            kospi_close=Decimal(3_000),
            kospi_ma200=Decimal(2_500),
            vkospi=Decimal(15),
            kospi_volatility_20d=Decimal("0.005"),
            previous_regime=RegimeStatus.DEFENSIVE,
            previous_raw_normal=[True],  # not enough history to confirm a 3-day streak
        )

        assert regime == RegimeStatus.DEFENSIVE

    def test_vkospi_missing_falls_back_to_20d_volatility_below_threshold(self) -> None:
        regime, signals = judge_regime(
            kospi_close=Decimal(3_000),
            kospi_ma200=Decimal(2_500),
            vkospi=None,
            kospi_volatility_20d=Decimal("0.01"),  # < 1.5% -> satisfied
            previous_regime=RegimeStatus.NORMAL,
            previous_raw_normal=[True],
        )

        assert regime == RegimeStatus.NORMAL
        assert signals["vkospi_available"] is False
        assert signals["volatility_condition"] is True

    def test_vkospi_missing_falls_back_to_20d_volatility_above_threshold(self) -> None:
        regime, signals = judge_regime(
            kospi_close=Decimal(3_000),
            kospi_ma200=Decimal(2_500),
            vkospi=None,
            kospi_volatility_20d=Decimal("0.02"),  # > 1.5% -> violated
            previous_regime=RegimeStatus.NORMAL,
            previous_raw_normal=[True],
        )

        assert regime == RegimeStatus.DEFENSIVE
        assert signals["raw_normal"] is False
