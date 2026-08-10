"""Pure factor calculation math (SoT A6.1 stage 2 — engine).

Deterministic, DB-free math only (SoT A2 원칙 7 — "숫자는 결정론적 코드"):
every function here takes already-fetched price/statement history and
returns raw factor values, so a future backtest engine can call the exact
same code path against arbitrary historical dates (SoT A6.7.6). All I/O —
fetching ``market_prices``/``financial_statements`` rows and upserting the
result into ``asset_factors`` — is ``src.workers.factor_calculation``'s job;
this module only imports ``src.domain``, per the layer contract
(``src.engine`` may depend on domain/adapters, never services/api/workers).

Momentum/Liquidity/Risk (price-based) functions fail *per-field*, not
per-asset: a field is ``None`` when its own window's history is too short
(SoT A6.7's 신규상장 종목 partial-history case is normal, unlike
``src.engine.market_regime``'s fail-closed ``InsufficientPriceHistoryError``
— that module judges *the whole market*, where a short KOSPI history is a
data outage, not a routine new-listing state). Quality/Value (financial-
statement-based) functions fail similarly — a ratio's denominator being
absent, zero, or negative (자본잠식/적자) makes the ratio itself ``None``
rather than a sign-flipped or infinite value.

The SoT A6.7.2 financial look-ahead bound (``disclosed_at <= as_of_date``)
is enforced structurally by ``FinancialStatementRepository.get_statement_history``'s
query filter, not by anything in this module — ``isolate_quarterly_income``/
``calculate_quality_factors`` only ever see statements already known to be
disclosed on or before ``as_of_date``.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.domain.financial_statement import DisclosedStatement, FiscalQuarter
from src.domain.market_price import PriceBar

_MOMENTUM_3M_WINDOW = 63
_MOMENTUM_6M_WINDOW = 126
_MOMENTUM_52W_WINDOW = 252
_MA20_WINDOW = 20
_VOLUME_CV_WINDOW = 20
_VOLATILITY_60D_WINDOW = 60
_MDD_60D_WINDOW = 60
_GAP_60D_WINDOW = 60
# SoT does not pin a gap threshold; hardcoded module constant like
# src.engine.market_regime's _VKOSPI_THRESHOLD — a future tuning target.
_GAP_THRESHOLD = Decimal("0.02")

# Explicit rank map (SoT A6.1 plan) — FiscalQuarter is a StrEnum whose
# member names sort alphabetically (ANNUAL, H1, Q1, Q3), which is NOT
# chronological order. Every quarter-ordering operation in this module goes
# through this map instead of the enum's own ordering.
_FISCAL_QUARTER_RANK: dict[FiscalQuarter, int] = {
    FiscalQuarter.Q1: 0,
    FiscalQuarter.H1: 1,
    FiscalQuarter.Q3: 2,
    FiscalQuarter.ANNUAL: 3,
}

_TTM_QUARTERS = 4


@dataclass(frozen=True)
class MomentumFactors:
    momentum_3m: Decimal | None
    momentum_6m: Decimal | None
    dist_52w_high: Decimal | None
    ma20_deviation: Decimal | None


@dataclass(frozen=True)
class LiquidityFactors:
    volume_cv: Decimal | None


@dataclass(frozen=True)
class RiskFactors:
    volatility_60d: Decimal | None
    mdd_60d: Decimal | None
    gap_frequency_60d: Decimal | None


@dataclass(frozen=True)
class IsolatedQuarter:
    """One fiscal year's standalone (non-cumulative) quarter, ``quarter`` 1-4.

    Income-statement fields (``revenue``/``operating_income``/``net_income``)
    are differenced from DART's cumulative reports (see
    ``isolate_quarterly_income``); balance-sheet fields
    (``total_assets``/``total_liabilities``/``total_equity``) are point-in-time
    snapshots passed through unchanged.
    """

    fiscal_year: int
    quarter: int
    revenue: Decimal | None
    operating_income: Decimal | None
    net_income: Decimal | None
    total_assets: Decimal | None
    total_liabilities: Decimal | None
    total_equity: Decimal | None
    disclosed_at: date


@dataclass(frozen=True)
class QualityFactors:
    roe: Decimal | None
    op_margin: Decimal | None
    revenue_growth_yoy: Decimal | None
    debt_ratio: Decimal | None
    # Exposed for calculate_value_factors's reuse (PER/PBR share these).
    net_income_ttm: Decimal | None
    total_equity_latest: Decimal | None
    # Observational only (see module docstring) — not a look-ahead gate.
    financial_data_as_of: date | None


@dataclass(frozen=True)
class ValueFactors:
    per: Decimal | None
    pbr: Decimal | None


def calculate_momentum(price_history: Sequence[PriceBar]) -> MomentumFactors:
    """``price_history`` must be oldest-first, trailing up to and including ``as_of_date``
    (the shape ``MarketPriceRepository.get_price_history`` returns).
    """
    return MomentumFactors(
        momentum_3m=_momentum_return(price_history, _MOMENTUM_3M_WINDOW),
        momentum_6m=_momentum_return(price_history, _MOMENTUM_6M_WINDOW),
        dist_52w_high=_dist_52w_high(price_history),
        ma20_deviation=_ma20_deviation(price_history),
    )


def _momentum_return(price_history: Sequence[PriceBar], window: int) -> Decimal | None:
    if len(price_history) < window + 1:
        return None
    base = price_history[-(window + 1)].adjusted_close
    if base == 0:
        return None
    return price_history[-1].adjusted_close / base - 1


def _dist_52w_high(price_history: Sequence[PriceBar]) -> Decimal | None:
    if len(price_history) < _MOMENTUM_52W_WINDOW:
        return None
    window = price_history[-_MOMENTUM_52W_WINDOW:]
    high_52w = max(bar.high for bar in window)
    if high_52w == 0:
        return None
    return window[-1].close / high_52w - 1


def _ma20_deviation(price_history: Sequence[PriceBar]) -> Decimal | None:
    if len(price_history) < _MA20_WINDOW:
        return None
    window = price_history[-_MA20_WINDOW:]
    ma20 = statistics.mean(bar.adjusted_close for bar in window)
    if ma20 == 0:
        return None
    return window[-1].close / ma20 - 1


def calculate_liquidity(price_history: Sequence[PriceBar]) -> LiquidityFactors:
    if len(price_history) < _VOLUME_CV_WINDOW:
        return LiquidityFactors(volume_cv=None)
    volumes = [Decimal(bar.volume) for bar in price_history[-_VOLUME_CV_WINDOW:]]
    mean_volume = statistics.mean(volumes)
    if mean_volume == 0:
        return LiquidityFactors(volume_cv=None)
    return LiquidityFactors(volume_cv=statistics.stdev(volumes) / mean_volume)


def calculate_risk(price_history: Sequence[PriceBar]) -> RiskFactors:
    return RiskFactors(
        volatility_60d=_volatility_60d(price_history),
        mdd_60d=_mdd_60d(price_history),
        gap_frequency_60d=_gap_frequency_60d(price_history),
    )


def _volatility_60d(price_history: Sequence[PriceBar]) -> Decimal | None:
    window_size = _VOLATILITY_60D_WINDOW + 1
    if len(price_history) < window_size:
        return None
    closes = [bar.adjusted_close for bar in price_history[-window_size:]]
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    return statistics.stdev(returns)


def _mdd_60d(price_history: Sequence[PriceBar]) -> Decimal | None:
    """Maximum drawdown over the trailing window — ``<= 0`` (0 if the window never fell
    below its running peak)."""
    if len(price_history) < _MDD_60D_WINDOW:
        return None
    closes = [bar.adjusted_close for bar in price_history[-_MDD_60D_WINDOW:]]
    peak = closes[0]
    max_drawdown = Decimal(0)
    for close in closes:
        peak = max(peak, close)
        if peak == 0:
            continue
        max_drawdown = min(max_drawdown, close / peak - 1)
    return max_drawdown


def _gap_frequency_60d(price_history: Sequence[PriceBar]) -> Decimal | None:
    window_size = _GAP_60D_WINDOW + 1
    if len(price_history) < window_size:
        return None
    window = price_history[-window_size:]
    eligible_days = 0
    gap_days = 0
    for i in range(1, len(window)):
        today = window[i]
        if today.halted:
            continue
        prev_close = window[i - 1].close
        eligible_days += 1
        if prev_close != 0 and abs(today.open - prev_close) / prev_close >= _GAP_THRESHOLD:
            gap_days += 1
    if eligible_days == 0:
        return None
    return Decimal(gap_days) / Decimal(eligible_days)


def _diff(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    """Isolate a standalone-quarter value from two cumulative DART figures.

    ``None`` if either operand is missing — no partial substitution (SoT
    A2 원칙 8): a missing prior-period baseline must not be silently
    treated as zero.
    """
    if current is None or prior is None:
        return None
    return current - prior


def isolate_quarterly_income(statements: Sequence[DisclosedStatement]) -> list[IsolatedQuarter]:
    """Convert DART's cumulative (YTD) half-year/9-month/annual figures into standalone quarters.

    Q1's report is already standalone. Q2 = H1 - Q1, Q3 = Q3-report - H1,
    Q4 = ANNUAL - Q3-report (DART has no standalone Q4 report — see
    ``FiscalQuarter``'s docstring). Balance-sheet fields are point-in-time
    snapshots, passed through unchanged rather than differenced. Output is
    chronologically ordered (oldest first) across every fiscal year present
    in ``statements``, ready for ``calculate_quality_factors``'s trailing-
    window math.
    """
    sorted_statements = sorted(
        statements, key=lambda s: (s.fiscal_year, _FISCAL_QUARTER_RANK[s.fiscal_quarter])
    )
    by_year: dict[int, dict[FiscalQuarter, DisclosedStatement]] = {}
    for statement in sorted_statements:
        by_year.setdefault(statement.fiscal_year, {})[statement.fiscal_quarter] = statement

    isolated: list[IsolatedQuarter] = []
    for fiscal_year in sorted(by_year):
        periods = by_year[fiscal_year]
        q1 = periods.get(FiscalQuarter.Q1)
        h1 = periods.get(FiscalQuarter.H1)
        q3 = periods.get(FiscalQuarter.Q3)
        annual = periods.get(FiscalQuarter.ANNUAL)

        if q1 is not None:
            isolated.append(
                IsolatedQuarter(
                    fiscal_year=fiscal_year,
                    quarter=1,
                    revenue=q1.revenue,
                    operating_income=q1.operating_income,
                    net_income=q1.net_income,
                    total_assets=q1.total_assets,
                    total_liabilities=q1.total_liabilities,
                    total_equity=q1.total_equity,
                    disclosed_at=q1.disclosed_at,
                )
            )
        if h1 is not None:
            isolated.append(
                IsolatedQuarter(
                    fiscal_year=fiscal_year,
                    quarter=2,
                    revenue=_diff(h1.revenue, q1.revenue if q1 else None),
                    operating_income=_diff(
                        h1.operating_income, q1.operating_income if q1 else None
                    ),
                    net_income=_diff(h1.net_income, q1.net_income if q1 else None),
                    total_assets=h1.total_assets,
                    total_liabilities=h1.total_liabilities,
                    total_equity=h1.total_equity,
                    disclosed_at=max(h1.disclosed_at, q1.disclosed_at) if q1 else h1.disclosed_at,
                )
            )
        if q3 is not None:
            isolated.append(
                IsolatedQuarter(
                    fiscal_year=fiscal_year,
                    quarter=3,
                    revenue=_diff(q3.revenue, h1.revenue if h1 else None),
                    operating_income=_diff(
                        q3.operating_income, h1.operating_income if h1 else None
                    ),
                    net_income=_diff(q3.net_income, h1.net_income if h1 else None),
                    total_assets=q3.total_assets,
                    total_liabilities=q3.total_liabilities,
                    total_equity=q3.total_equity,
                    disclosed_at=max(q3.disclosed_at, h1.disclosed_at) if h1 else q3.disclosed_at,
                )
            )
        if annual is not None:
            isolated.append(
                IsolatedQuarter(
                    fiscal_year=fiscal_year,
                    quarter=4,
                    revenue=_diff(annual.revenue, q3.revenue if q3 else None),
                    operating_income=_diff(
                        annual.operating_income, q3.operating_income if q3 else None
                    ),
                    net_income=_diff(annual.net_income, q3.net_income if q3 else None),
                    total_assets=annual.total_assets,
                    total_liabilities=annual.total_liabilities,
                    total_equity=annual.total_equity,
                    disclosed_at=(
                        max(annual.disclosed_at, q3.disclosed_at) if q3 else annual.disclosed_at
                    ),
                )
            )
    return isolated


def _sum_recent(values: Sequence[Decimal | None], n: int) -> Decimal | None:
    """Sum the trailing ``n`` values — ``None`` if fewer than ``n`` are available or any
    of them is ``None`` (no partial sum, SoT A2 원칙 8)."""
    if len(values) < n:
        return None
    window = values[-n:]
    if any(v is None for v in window):
        return None
    return sum((v for v in window if v is not None), start=Decimal(0))


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    """``None`` if either operand is missing or the denominator is ``<= 0`` — a
    non-positive denominator (자본잠식/무매출) makes the ratio undefined or
    misleading rather than a sign-flipped or infinite value."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _yoy_growth(isolated_quarters: Sequence[IsolatedQuarter]) -> Decimal | None:
    revenues = [q.revenue for q in isolated_quarters]
    current_ttm = _sum_recent(revenues, _TTM_QUARTERS)
    prior_ttm = _sum_recent(revenues[:-_TTM_QUARTERS], _TTM_QUARTERS)
    if current_ttm is None or prior_ttm is None or prior_ttm <= 0:
        return None
    return current_ttm / prior_ttm - 1


def calculate_quality_factors(isolated_quarters: Sequence[IsolatedQuarter]) -> QualityFactors:
    """``isolated_quarters`` must be chronologically ordered (oldest first) — the shape
    ``isolate_quarterly_income`` returns."""
    latest = isolated_quarters[-1] if isolated_quarters else None
    total_equity_latest = latest.total_equity if latest is not None else None
    total_liabilities_latest = latest.total_liabilities if latest is not None else None

    net_income_ttm = _sum_recent([q.net_income for q in isolated_quarters], _TTM_QUARTERS)
    operating_income_ttm = _sum_recent(
        [q.operating_income for q in isolated_quarters], _TTM_QUARTERS
    )
    revenue_ttm = _sum_recent([q.revenue for q in isolated_quarters], _TTM_QUARTERS)

    financial_data_as_of = (
        max(q.disclosed_at for q in isolated_quarters[-_TTM_QUARTERS:])
        if len(isolated_quarters) >= _TTM_QUARTERS
        else None
    )

    return QualityFactors(
        roe=_ratio(net_income_ttm, total_equity_latest),
        op_margin=_ratio(operating_income_ttm, revenue_ttm),
        revenue_growth_yoy=_yoy_growth(isolated_quarters),
        debt_ratio=_ratio(total_liabilities_latest, total_equity_latest),
        net_income_ttm=net_income_ttm,
        total_equity_latest=total_equity_latest,
        financial_data_as_of=financial_data_as_of,
    )


def calculate_value_factors(
    *,
    market_cap: Decimal | None,
    net_income_ttm: Decimal | None,
    total_equity_latest: Decimal | None,
) -> ValueFactors:
    """PER/PBR from ``QualityFactors.net_income_ttm``/``total_equity_latest`` (reused,
    not recomputed) and the universe snapshot's ``market_cap``. ``None`` whenever the
    respective denominator is missing or ``<= 0`` (적자/자본잠식 종목의 무의미한 배수
    방지) — same rationale as ``_ratio``.
    """
    return ValueFactors(
        per=_ratio(market_cap, net_income_ttm),
        pbr=_ratio(market_cap, total_equity_latest),
    )
