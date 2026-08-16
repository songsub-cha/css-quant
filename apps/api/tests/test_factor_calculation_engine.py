"""Unit tests for ``src.engine.factor_calculation`` (SoT A6.1 stage 2).

Pure DB-free math — no fakes, no fixtures, just already-fetched
``PriceBar``/``DisclosedStatement`` sequences and asserted outputs. Mirrors
``test_market_regime_engine.py``'s style: where a formula is nontrivial
(stdev, YoY growth), the expected value is computed with the same formula
the implementation uses rather than a hand-typed magic number, matching
that file's ``test_matches_stdev_of_trailing_20_daily_returns`` pattern.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal

from src.domain.financial_statement import DisclosedStatement, FiscalQuarter
from src.domain.market_price import PriceBar
from src.engine.factor_calculation import (
    IsolatedQuarter,
    calculate_liquidity,
    calculate_momentum,
    calculate_quality_factors,
    calculate_risk,
    calculate_value_factors,
    isolate_quarterly_income,
)


def _bar(
    d: date,
    *,
    close: Decimal,
    high: Decimal | None = None,
    open_: Decimal | None = None,
    adjusted_close: Decimal | None = None,
    volume: int = 1_000_000,
    halted: bool = False,
) -> PriceBar:
    return PriceBar(
        date=d,
        open=open_ if open_ is not None else close,
        high=high if high is not None else close,
        low=close,
        close=close,
        adjusted_close=adjusted_close if adjusted_close is not None else close,
        volume=volume,
        trading_value=close * volume,
        halted=halted,
    )


def _statement(
    fiscal_year: int,
    fiscal_quarter: FiscalQuarter,
    *,
    revenue: Decimal | None = None,
    operating_income: Decimal | None = None,
    net_income: Decimal | None = None,
    total_assets: Decimal | None = None,
    total_liabilities: Decimal | None = None,
    total_equity: Decimal | None = None,
    disclosed_at: date,
) -> DisclosedStatement:
    return DisclosedStatement(
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        disclosed_at=disclosed_at,
    )


def _iq(
    fiscal_year: int,
    quarter: int,
    *,
    revenue: Decimal | None = None,
    operating_income: Decimal | None = None,
    net_income: Decimal | None = None,
    total_assets: Decimal | None = None,
    total_liabilities: Decimal | None = None,
    total_equity: Decimal | None = None,
    disclosed_at: date,
) -> IsolatedQuarter:
    return IsolatedQuarter(
        fiscal_year=fiscal_year,
        quarter=quarter,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        disclosed_at=disclosed_at,
    )


def _build_full_momentum_history() -> list[PriceBar]:
    start = date(2025, 1, 1)
    bars = [
        _bar(
            start + timedelta(days=i),
            close=Decimal(100 + i),
            high=Decimal(100 + i),
            adjusted_close=Decimal(100 + i),
        )
        for i in range(252)
    ]
    # Intraday spike far above the trend (raw high only) -> a clear 52-week high.
    bars[200] = bars[200].model_copy(update={"high": Decimal(500)})
    # Last day's raw close drops well below that high; adjusted_close stays
    # on-trend so momentum_3m/6m still reflect the underlying growth.
    bars[-1] = bars[-1].model_copy(update={"close": Decimal(300)})
    return bars


class TestCalculateMomentum:
    def test_all_fields_none_on_empty_history(self) -> None:
        result = calculate_momentum([])

        assert result.momentum_3m is None
        assert result.momentum_6m is None
        assert result.dist_52w_high is None
        assert result.ma20_deviation is None

    def test_only_ma20_deviation_computed_with_exactly_20_bars(self) -> None:
        """Per-field nullability (SoT A6.7 신규상장): a field with enough history
        computes while the others stay None, rather than the whole struct failing."""
        start = date(2025, 1, 1)
        bars = [
            _bar(start + timedelta(days=i), close=Decimal(100), adjusted_close=Decimal(100))
            for i in range(19)
        ]
        bars.append(
            _bar(start + timedelta(days=19), close=Decimal(120), adjusted_close=Decimal(120))
        )

        result = calculate_momentum(bars)

        assert result.momentum_3m is None
        assert result.momentum_6m is None
        assert result.dist_52w_high is None
        expected_ma20 = (Decimal(100) * 19 + Decimal(120)) / 20
        assert result.ma20_deviation == Decimal(120) / expected_ma20 - 1

    def test_full_history_computes_all_four_fields(self) -> None:
        bars = _build_full_momentum_history()

        result = calculate_momentum(bars)

        expected_momentum_3m = bars[-1].adjusted_close / bars[-64].adjusted_close - 1
        expected_momentum_6m = bars[-1].adjusted_close / bars[-127].adjusted_close - 1
        expected_high_52w = max(b.high for b in bars)
        expected_dist = bars[-1].close / expected_high_52w - 1
        expected_ma20 = statistics.mean(b.adjusted_close for b in bars[-20:])
        expected_ma20_deviation = bars[-1].close / expected_ma20 - 1

        assert result.momentum_3m == expected_momentum_3m
        assert result.momentum_6m == expected_momentum_6m
        assert result.dist_52w_high == expected_dist
        assert result.dist_52w_high < 0
        assert result.ma20_deviation == expected_ma20_deviation


class TestCalculateLiquidity:
    def test_none_when_fewer_than_20_bars(self) -> None:
        start = date(2025, 1, 1)
        bars = [_bar(start + timedelta(days=i), close=Decimal(100), volume=1000) for i in range(19)]

        result = calculate_liquidity(bars)

        assert result.volume_cv is None

    def test_matches_stdev_over_mean_of_trailing_20_volumes(self) -> None:
        start = date(2025, 1, 1)
        volumes = [1000] * 19 + [4000]
        bars = [
            _bar(start + timedelta(days=i), close=Decimal(100), volume=v)
            for i, v in enumerate(volumes)
        ]

        result = calculate_liquidity(bars)

        decimal_volumes = [Decimal(v) for v in volumes]
        expected = statistics.stdev(decimal_volumes) / statistics.mean(decimal_volumes)
        assert result.volume_cv == expected

    def test_ignores_extra_leading_history(self) -> None:
        start = date(2025, 1, 1)
        leading = [
            _bar(start + timedelta(days=i), close=Decimal(100), volume=999_999) for i in range(10)
        ]
        trailing = [
            _bar(start + timedelta(days=10 + i), close=Decimal(100), volume=2000) for i in range(20)
        ]

        result = calculate_liquidity(leading + trailing)

        assert result.volume_cv == Decimal(0)


class TestCalculateRisk:
    def test_all_fields_none_when_history_insufficient(self) -> None:
        start = date(2025, 1, 1)
        bars = [_bar(start + timedelta(days=i), close=Decimal(100)) for i in range(59)]

        result = calculate_risk(bars)

        assert result.volatility_60d is None
        assert result.mdd_60d is None
        assert result.gap_frequency_60d is None

    def test_volatility_60d_matches_stdev_of_trailing_60_returns(self) -> None:
        start = date(2025, 1, 1)
        raw = [10_000, 10_100, 9_950, 10_080, 9_970] * 12 + [10_050]  # 61 closes
        bars = [
            _bar(start + timedelta(days=i), close=Decimal(v), adjusted_close=Decimal(v))
            for i, v in enumerate(raw)
        ]

        result = calculate_risk(bars)

        expected_returns = [Decimal(raw[i]) / Decimal(raw[i - 1]) - 1 for i in range(1, len(raw))]
        assert result.volatility_60d == statistics.stdev(expected_returns)

    def test_mdd_60d_computes_max_drawdown_from_running_peak(self) -> None:
        start = date(2025, 1, 1)
        # Peak 100 on day0, falls to 70 (-30%), recovers to 99 -- peak never
        # exceeds 100, so the trough is unambiguously the max drawdown.
        values = [100] + [100 - i for i in range(1, 31)] + [70 + i for i in range(1, 30)]
        assert len(values) == 60
        bars = [
            _bar(start + timedelta(days=i), close=Decimal(v), adjusted_close=Decimal(v))
            for i, v in enumerate(values)
        ]

        result = calculate_risk(bars)

        assert result.mdd_60d == Decimal(70) / Decimal(100) - 1

    def test_gap_frequency_60d_counts_days_at_or_above_threshold(self) -> None:
        start = date(2025, 1, 1)
        bars = [_bar(start, close=Decimal(100), open_=Decimal(100))]
        for i in range(1, 61):
            gap = i <= 3
            open_price = Decimal(103) if gap else Decimal(100)
            bars.append(_bar(start + timedelta(days=i), close=Decimal(100), open_=open_price))

        result = calculate_risk(bars)

        assert result.gap_frequency_60d == Decimal(3) / Decimal(60)

    def test_gap_frequency_60d_excludes_halted_days_from_numerator_and_denominator(self) -> None:
        start = date(2025, 1, 1)
        bars = [_bar(start, close=Decimal(100), open_=Decimal(100))]
        for i in range(1, 61):
            gap = i <= 3
            halted = i == 1
            open_price = Decimal(103) if gap else Decimal(100)
            bars.append(
                _bar(start + timedelta(days=i), close=Decimal(100), open_=open_price, halted=halted)
            )

        result = calculate_risk(bars)

        # Day 1 (a gap day) is halted -> excluded from both: 2 gap days / 59 eligible.
        assert result.gap_frequency_60d == Decimal(2) / Decimal(59)


class TestIsolateQuarterlyIncome:
    def test_q1_passes_through_unchanged(self) -> None:
        statements = [
            _statement(
                2025,
                FiscalQuarter.Q1,
                revenue=Decimal(100),
                operating_income=Decimal(20),
                net_income=Decimal(15),
                total_assets=Decimal(1000),
                total_liabilities=Decimal(400),
                total_equity=Decimal(600),
                disclosed_at=date(2025, 5, 15),
            )
        ]

        (result,) = isolate_quarterly_income(statements)

        assert result.fiscal_year == 2025
        assert result.quarter == 1
        assert result.revenue == Decimal(100)
        assert result.operating_income == Decimal(20)
        assert result.net_income == Decimal(15)
        assert result.total_assets == Decimal(1000)
        assert result.total_liabilities == Decimal(400)
        assert result.total_equity == Decimal(600)
        assert result.disclosed_at == date(2025, 5, 15)

    def test_h1_q3_annual_are_differenced_from_cumulative(self) -> None:
        statements = [
            _statement(
                2025,
                FiscalQuarter.Q1,
                revenue=Decimal(100),
                operating_income=Decimal(20),
                net_income=Decimal(15),
                total_equity=Decimal(600),
                disclosed_at=date(2025, 5, 15),
            ),
            _statement(
                2025,
                FiscalQuarter.H1,
                revenue=Decimal(250),
                operating_income=Decimal(45),
                net_income=Decimal(30),
                total_equity=Decimal(650),
                disclosed_at=date(2025, 8, 14),
            ),
            _statement(
                2025,
                FiscalQuarter.Q3,
                revenue=Decimal(400),
                operating_income=Decimal(70),
                net_income=Decimal(50),
                total_equity=Decimal(700),
                disclosed_at=date(2025, 11, 14),
            ),
            _statement(
                2025,
                FiscalQuarter.ANNUAL,
                revenue=Decimal(600),
                operating_income=Decimal(100),
                net_income=Decimal(80),
                total_equity=Decimal(750),
                disclosed_at=date(2026, 3, 31),
            ),
        ]

        result = isolate_quarterly_income(statements)

        assert [(q.fiscal_year, q.quarter) for q in result] == [
            (2025, 1),
            (2025, 2),
            (2025, 3),
            (2025, 4),
        ]
        q1, q2, q3, q4 = result
        assert (q1.revenue, q1.operating_income, q1.net_income) == (
            Decimal(100),
            Decimal(20),
            Decimal(15),
        )
        assert (q2.revenue, q2.operating_income, q2.net_income) == (
            Decimal(150),
            Decimal(25),
            Decimal(15),
        )
        assert (q3.revenue, q3.operating_income, q3.net_income) == (
            Decimal(150),
            Decimal(25),
            Decimal(20),
        )
        assert (q4.revenue, q4.operating_income, q4.net_income) == (
            Decimal(200),
            Decimal(30),
            Decimal(30),
        )
        # Balance-sheet fields pass through from the cumulative statement's
        # own snapshot -- never differenced.
        assert q2.total_equity == Decimal(650)
        assert q3.total_equity == Decimal(700)
        assert q4.total_equity == Decimal(750)
        assert q1.disclosed_at == date(2025, 5, 15)
        assert q2.disclosed_at == date(2025, 8, 14)
        assert q3.disclosed_at == date(2025, 11, 14)
        assert q4.disclosed_at == date(2026, 3, 31)

    def test_missing_prior_period_propagates_none_without_partial_substitution(self) -> None:
        # No Q1, no ANNUAL -- only H1 and Q3 disclosed this year.
        statements = [
            _statement(
                2025,
                FiscalQuarter.H1,
                revenue=Decimal(250),
                operating_income=Decimal(45),
                net_income=Decimal(30),
                total_equity=Decimal(650),
                disclosed_at=date(2025, 8, 14),
            ),
            _statement(
                2025,
                FiscalQuarter.Q3,
                revenue=Decimal(400),
                operating_income=Decimal(70),
                net_income=Decimal(50),
                total_equity=Decimal(700),
                disclosed_at=date(2025, 11, 14),
            ),
        ]

        result = isolate_quarterly_income(statements)

        assert [(q.fiscal_year, q.quarter) for q in result] == [(2025, 2), (2025, 3)]
        q2, q3 = result
        # Q2 = H1 - Q1, but Q1 is missing entirely -> None, not H1 itself.
        assert q2.revenue is None
        assert q2.operating_income is None
        assert q2.net_income is None
        assert q2.total_equity == Decimal(650)  # snapshot still passes through
        assert q2.disclosed_at == date(2025, 8, 14)  # only H1's own row was used
        # Q3 = Q3 - H1, and H1 is present -> computes normally.
        assert q3.revenue == Decimal(150)
        assert q3.operating_income == Decimal(25)
        assert q3.net_income == Decimal(20)

    def test_sorts_chronologically_across_years_regardless_of_input_order(self) -> None:
        # Deliberately scrambled input order across two fiscal years.
        statements = [
            _statement(
                2026, FiscalQuarter.ANNUAL, revenue=Decimal(1), disclosed_at=date(2027, 3, 31)
            ),
            _statement(2025, FiscalQuarter.Q1, revenue=Decimal(1), disclosed_at=date(2025, 5, 15)),
            _statement(2026, FiscalQuarter.Q1, revenue=Decimal(1), disclosed_at=date(2026, 5, 15)),
            _statement(
                2025, FiscalQuarter.ANNUAL, revenue=Decimal(1), disclosed_at=date(2026, 3, 31)
            ),
        ]

        result = isolate_quarterly_income(statements)

        assert [(q.fiscal_year, q.quarter) for q in result] == [
            (2025, 1),
            (2025, 4),
            (2026, 1),
            (2026, 4),
        ]


class TestCalculateQualityFactors:
    def test_ttm_none_when_fewer_than_4_quarters(self) -> None:
        quarters = [
            _iq(
                2025,
                q,
                net_income=Decimal(10),
                revenue=Decimal(100),
                operating_income=Decimal(20),
                total_equity=Decimal(500),
                total_liabilities=Decimal(200),
                disclosed_at=date(2025, q * 3, 1),
            )
            for q in range(1, 4)
        ]

        result = calculate_quality_factors(quarters)

        assert result.net_income_ttm is None
        assert result.roe is None  # needs net_income_ttm
        assert result.op_margin is None  # needs revenue_ttm/operating_income_ttm
        assert result.financial_data_as_of is None
        # total_equity_latest/total_liabilities_latest are plain latest-quarter
        # snapshots, not TTM sums -- available from a single quarter, so
        # debt_ratio (which only needs those two) still computes.
        assert result.total_equity_latest == Decimal(500)
        assert result.debt_ratio == Decimal(200) / Decimal(500)

    def test_ttm_partial_sum_forbidden_when_one_quarter_missing_net_income(self) -> None:
        quarters = [
            _iq(
                2025,
                1,
                net_income=Decimal(10),
                revenue=Decimal(100),
                operating_income=Decimal(20),
                total_equity=Decimal(500),
                total_liabilities=Decimal(200),
                disclosed_at=date(2025, 5, 1),
            ),
            _iq(
                2025,
                2,
                net_income=None,
                revenue=Decimal(110),
                operating_income=Decimal(22),
                total_equity=Decimal(510),
                total_liabilities=Decimal(205),
                disclosed_at=date(2025, 8, 1),
            ),
            _iq(
                2025,
                3,
                net_income=Decimal(12),
                revenue=Decimal(115),
                operating_income=Decimal(23),
                total_equity=Decimal(520),
                total_liabilities=Decimal(210),
                disclosed_at=date(2025, 11, 1),
            ),
            _iq(
                2025,
                4,
                net_income=Decimal(13),
                revenue=Decimal(120),
                operating_income=Decimal(24),
                total_equity=Decimal(530),
                total_liabilities=Decimal(215),
                disclosed_at=date(2026, 3, 1),
            ),
        ]

        result = calculate_quality_factors(quarters)

        assert result.net_income_ttm is None
        assert result.roe is None
        # op_margin/debt_ratio use different fields, all present in every
        # quarter -- unaffected by the missing net_income.
        expected_op_margin = (Decimal(20) + Decimal(22) + Decimal(23) + Decimal(24)) / (
            Decimal(100) + Decimal(110) + Decimal(115) + Decimal(120)
        )
        assert result.op_margin == expected_op_margin
        assert result.total_equity_latest == Decimal(530)
        assert result.debt_ratio == Decimal(215) / Decimal(530)
        assert result.financial_data_as_of == date(2026, 3, 1)

    def test_roe_and_debt_ratio_none_when_latest_equity_nonpositive(self) -> None:
        quarters = [
            _iq(
                2025,
                q,
                net_income=Decimal(10),
                revenue=Decimal(100),
                operating_income=Decimal(20),
                total_equity=Decimal(-50) if q == 4 else Decimal(500),
                total_liabilities=Decimal(200),
                disclosed_at=date(2025, q * 3, 1),
            )
            for q in range(1, 5)
        ]

        result = calculate_quality_factors(quarters)

        assert result.total_equity_latest == Decimal(-50)
        assert result.roe is None
        assert result.debt_ratio is None
        assert result.op_margin is not None  # revenue_ttm > 0, unaffected by equity

    def test_op_margin_none_when_revenue_ttm_is_zero(self) -> None:
        quarters = [
            _iq(
                2025,
                q,
                net_income=Decimal(10),
                revenue=Decimal(0),
                operating_income=Decimal(5),
                total_equity=Decimal(500),
                total_liabilities=Decimal(100),
                disclosed_at=date(2025, q * 3, 1),
            )
            for q in range(1, 5)
        ]

        result = calculate_quality_factors(quarters)

        assert result.op_margin is None
        assert result.roe == Decimal(40) / Decimal(500)

    def test_revenue_growth_yoy_none_with_fewer_than_8_quarters(self) -> None:
        quarters = [
            _iq(2025, q, revenue=Decimal(100), disclosed_at=date(2025, q * 3, 1))
            for q in range(1, 5)
        ]

        result = calculate_quality_factors(quarters)

        assert result.revenue_growth_yoy is None

    def test_revenue_growth_yoy_computed_with_8_quarters(self) -> None:
        quarters = [
            _iq(2024, q, revenue=Decimal(100), disclosed_at=date(2024, q * 3, 1))
            for q in range(1, 5)
        ] + [
            _iq(2025, q, revenue=Decimal(120), disclosed_at=date(2025, q * 3, 1))
            for q in range(1, 5)
        ]

        result = calculate_quality_factors(quarters)

        assert result.revenue_growth_yoy == Decimal(480) / Decimal(400) - 1


class TestCalculateValueFactors:
    def test_per_and_pbr_computed(self) -> None:
        result = calculate_value_factors(
            market_cap=Decimal(1000), net_income_ttm=Decimal(50), total_equity_latest=Decimal(400)
        )

        assert result.per == Decimal(1000) / Decimal(50)
        assert result.pbr == Decimal(1000) / Decimal(400)

    def test_per_none_when_net_income_ttm_nonpositive_or_missing(self) -> None:
        for net_income_ttm in (Decimal(0), Decimal(-10), None):
            result = calculate_value_factors(
                market_cap=Decimal(1000),
                net_income_ttm=net_income_ttm,
                total_equity_latest=Decimal(400),
            )
            assert result.per is None

    def test_pbr_none_when_total_equity_nonpositive_or_missing(self) -> None:
        for total_equity_latest in (Decimal(0), Decimal(-10), None):
            result = calculate_value_factors(
                market_cap=Decimal(1000),
                net_income_ttm=Decimal(50),
                total_equity_latest=total_equity_latest,
            )
            assert result.pbr is None

    def test_none_when_market_cap_missing(self) -> None:
        result = calculate_value_factors(
            market_cap=None, net_income_ttm=Decimal(50), total_equity_latest=Decimal(400)
        )

        assert result.per is None
        assert result.pbr is None
