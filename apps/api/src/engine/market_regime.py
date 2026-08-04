"""Pure market regime + market-shock calculations (SoT A6.2/A6.3 — engine).

Deterministic, DB-free math only (SoT A2 principle 7 — "숫자는 결정론적
코드"): every function here takes already-fetched values/sequences and
returns a verdict, so a future backtest engine can call the exact same code
path against arbitrary historical dates (SoT A6.7.6). All I/O — fetching
``index_prices``/``market_regimes`` rows and upserting the result — is
``src.workers.market_regime_detection``'s job; this module only imports
``src.domain`` (for ``RegimeStatus``/``InsufficientPriceHistoryError``), per
the layer contract (``src.engine`` may depend on domain/adapters, never
services/api/workers).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from src.domain.market_regime import InsufficientPriceHistoryError, RegimeStatus

_MA200_WINDOW = 200
_VOLATILITY_RETURNS_WINDOW = 20
_VKOSPI_THRESHOLD = Decimal("25")
_VOLATILITY_THRESHOLD = Decimal("0.015")
_SHOCK_KOSPI_DROP_THRESHOLD = Decimal("-0.03")
_SHOCK_VKOSPI_MULTIPLIER = Decimal("1.5")
_HYSTERESIS_STREAK = 3


def calculate_ma200(closes: Sequence[Decimal]) -> Decimal:
    """200-day simple moving average of KOSPI closes (SoT A6.2).

    ``closes`` must be oldest-first (the order ``IndexPriceRepository.get_recent``
    already returns) with at least 200 entries; only the trailing 200 are
    used. Fail-closed (SoT A2 principle 8 / A6.4): raises
    ``InsufficientPriceHistoryError`` rather than averaging a short window.
    """
    if len(closes) < _MA200_WINDOW:
        raise InsufficientPriceHistoryError(
            f"need at least {_MA200_WINDOW} KOSPI closes for the 200-day MA, got {len(closes)}"
        )
    return statistics.mean(closes[-_MA200_WINDOW:])


def calculate_volatility_20d(closes: Sequence[Decimal]) -> Decimal:
    """20-day KOSPI daily-return volatility — SoT A6.2's VKOSPI-missing fallback.

    Returned on the same *daily* scale as the SoT's ``< 1.5%`` threshold —
    NOT annualized. ``closes`` must be oldest-first with at least 21 entries
    (20 daily returns need 21 closing prices); only the trailing 21 are
    used. Fail-closed like ``calculate_ma200``.
    """
    window_size = _VOLATILITY_RETURNS_WINDOW + 1
    if len(closes) < window_size:
        raise InsufficientPriceHistoryError(
            f"need at least {window_size} KOSPI closes for 20-day volatility, got {len(closes)}"
        )
    window = closes[-window_size:]
    returns = [window[i] / window[i - 1] - 1 for i in range(1, len(window))]
    return statistics.stdev(returns)


def detect_market_shock(
    *,
    kospi_prev_close: Decimal,
    kospi_close: Decimal,
    vkospi: Decimal | None,
    vkospi_history_20d: Sequence[Decimal],
) -> tuple[bool, dict[str, Any]]:
    """SoT A6.3: KOSPI -3%+ same-day drop OR VKOSPI > 1.5x its trailing 20-day average.

    Each leg is evaluated independently and only when its inputs are
    present — a missing ``vkospi`` bar or an empty ``vkospi_history_20d``
    (VKOSPI collection gap) skips only that leg rather than failing the
    whole judgement; unlike the 200-day KOSPI MA, market-shock detection has
    no fail-closed requirement in the SoT. ``vkospi_history_20d`` must NOT
    include today's own ``vkospi`` bar — it is the baseline today's value is
    compared against, so including it would let a shock day inflate its own
    threshold.

    Returns ``(market_shock, signals)`` where ``signals`` carries every
    leg's raw inputs and per-leg verdict, satisfying the "signals에 각 leg의
    raw 값과 충족 여부가 남는다" acceptance criterion.
    """
    kospi_change_pct = kospi_close / kospi_prev_close - 1
    kospi_shock = kospi_change_pct <= _SHOCK_KOSPI_DROP_THRESHOLD

    vkospi_avg_20d: Decimal | None = None
    vkospi_threshold: Decimal | None = None
    vkospi_shock: bool | None = None
    if vkospi is not None and vkospi_history_20d:
        vkospi_avg_20d = statistics.mean(vkospi_history_20d)
        vkospi_threshold = vkospi_avg_20d * _SHOCK_VKOSPI_MULTIPLIER
        vkospi_shock = vkospi > vkospi_threshold

    market_shock = kospi_shock or bool(vkospi_shock)
    signals = {
        "kospi_prev_close": float(kospi_prev_close),
        "kospi_close": float(kospi_close),
        "kospi_change_pct": float(kospi_change_pct),
        "kospi_shock": kospi_shock,
        "vkospi": float(vkospi) if vkospi is not None else None,
        "vkospi_avg_20d": float(vkospi_avg_20d) if vkospi_avg_20d is not None else None,
        "vkospi_threshold": float(vkospi_threshold) if vkospi_threshold is not None else None,
        "vkospi_shock": vkospi_shock,
    }
    return market_shock, signals


def judge_regime(
    *,
    kospi_close: Decimal,
    kospi_ma200: Decimal,
    vkospi: Decimal | None,
    kospi_volatility_20d: Decimal,
    previous_regime: RegimeStatus | None,
    previous_raw_normal: Sequence[bool],
) -> tuple[RegimeStatus, dict[str, Any]]:
    """SoT A6.2's NORMAL/DEFENSIVE judgement with hysteresis + cold start.

    ``previous_raw_normal`` is the raw (pre-hysteresis) NORMAL-condition
    verdict of the trading days immediately before today, most-recent-first
    (i.e. ``[yesterday, day_before_yesterday]``) — read back from
    ``signals["raw_normal"]`` on the rows ``MarketRegimeRepository.get_recent``
    returns, NOT the hysteresis-applied ``regime`` column. Counting against
    the raw column (rather than ``regime``) is what lets a DEFENSIVE streak
    end exactly on the 3rd consecutive day the raw condition is satisfied,
    instead of never converging because ``regime`` itself stayed DEFENSIVE
    the whole time. Fewer than 2 entries can never satisfy the 3-day streak
    (today + 2 priors).

    Returns ``(regime, signals)`` where ``signals`` carries today's raw
    verdict and its two sub-conditions — this dict is what a later day's
    ``previous_raw_normal`` is built from, so its ``"raw_normal"`` key is
    load-bearing, not just diagnostic.
    """
    kospi_above_ma200 = kospi_close > kospi_ma200
    vkospi_condition: bool | None = None
    if vkospi is not None:
        vkospi_condition = vkospi < _VKOSPI_THRESHOLD
    volatility_condition = kospi_volatility_20d < _VOLATILITY_THRESHOLD
    secondary_condition = vkospi_condition if vkospi_condition is not None else volatility_condition
    raw_normal = kospi_above_ma200 and secondary_condition

    if previous_regime is None:
        regime = RegimeStatus.DEFENSIVE  # cold start (SoT A6.2)
    elif previous_regime == RegimeStatus.NORMAL:
        regime = RegimeStatus.NORMAL if raw_normal else RegimeStatus.DEFENSIVE
    else:
        required_priors = _HYSTERESIS_STREAK - 1
        streak = (
            raw_normal
            and len(previous_raw_normal) >= required_priors
            and all(previous_raw_normal[:required_priors])
        )
        regime = RegimeStatus.NORMAL if streak else RegimeStatus.DEFENSIVE

    signals = {
        "raw_normal": raw_normal,
        "kospi_above_ma200": kospi_above_ma200,
        "vkospi_condition": vkospi_condition,
        "volatility_condition": volatility_condition,
        "vkospi_available": vkospi is not None,
    }
    return regime, signals
