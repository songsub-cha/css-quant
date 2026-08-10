"""Market regime + market-shock detection orchestration (SoT A6.2/A6.3 — workers).

The lint-imports layer contract puts this here rather than in
``src/services``: ``src.services``' ``forbidden_modules`` includes
``src.engine`` (``apps/api/pyproject.toml``), so an orchestrator that calls
``src.engine.market_regime``'s pure judgement functions cannot live in
services. ``src.workers``' contract only forbids ``src.api``, so this module
is the legal home — matching SoT D6's ``detect_regime`` being a scheduled
batch job, and the same shape as ``src.workers.backfill_cli.execute_backfill``
(every dependency injected already-built, Protocol-typed, so this is
testable end-to-end with in-memory fakes, no live DB).

Registering ``detect_market_regime`` as an actual Arq cron job and recording
its runs in ``job_runs`` is issue #39's scope — this module only provides
the callable pipeline: fetch KOSPI/VKOSPI history -> judge -> upsert.
"""

from __future__ import annotations

from datetime import date

from src.domain.index_price import IndexCode, IndexPriceRepository
from src.domain.market_regime import (
    InsufficientPriceHistoryError,
    MarketRegime,
    MarketRegimeInfo,
    MarketRegimeRepository,
)
from src.engine.market_regime import (
    calculate_ma200,
    calculate_volatility_20d,
    detect_market_shock,
    judge_regime,
)

# SoT A6.2: 200-day KOSPI MA. calculate_volatility_20d needs 21 closes (20
# daily returns), well within this window, so one fetch covers both.
_KOSPI_HISTORY_WINDOW = 200

# 20-day VKOSPI average (SoT A6.3) plus today's own bar.
_VKOSPI_AVG_WINDOW = 20
_VKOSPI_FETCH_WINDOW = _VKOSPI_AVG_WINDOW + 1

# SoT A6.2 hysteresis: DEFENSIVE -> NORMAL needs 3 consecutive raw-satisfied
# days (today + this many priors).
_REGIME_HYSTERESIS_LOOKBACK = 2


async def detect_market_regime(
    index_price_repo: IndexPriceRepository,
    market_regime_repo: MarketRegimeRepository,
    as_of_date: date,
) -> MarketRegime:
    """Fetch, judge, and persist one trading day's market regime + shock verdict.

    Re-running with the same ``as_of_date`` against unchanged
    ``index_prices``/``market_regimes`` data reproduces the same result
    (upsert is idempotent, and every input here is already-committed
    history — no "today so far" partial data).
    """
    kospi_bars = await index_price_repo.get_recent(
        index_code=IndexCode.KOSPI, end_date=as_of_date, limit=_KOSPI_HISTORY_WINDOW
    )
    if len(kospi_bars) < _KOSPI_HISTORY_WINDOW or kospi_bars[-1].date != as_of_date:
        raise InsufficientPriceHistoryError(
            f"need {_KOSPI_HISTORY_WINDOW} KOSPI trading days up to and including"
            f" {as_of_date}, got {len(kospi_bars)}"
            + (
                " with none dated as_of_date"
                if kospi_bars and kospi_bars[-1].date != as_of_date
                else ""
            )
        )
    kospi_closes = [bar.close for bar in kospi_bars]
    kospi_close = kospi_closes[-1]
    kospi_prev_close = kospi_closes[-2]
    kospi_ma200 = calculate_ma200(kospi_closes)
    kospi_volatility_20d = calculate_volatility_20d(kospi_closes)

    vkospi_bars = await index_price_repo.get_recent(
        index_code=IndexCode.VKOSPI, end_date=as_of_date, limit=_VKOSPI_FETCH_WINDOW
    )
    has_today_vkospi = bool(vkospi_bars) and vkospi_bars[-1].date == as_of_date
    vkospi = vkospi_bars[-1].close if has_today_vkospi else None
    vkospi_history_bars = vkospi_bars[:-1] if has_today_vkospi else vkospi_bars
    vkospi_history_20d = [bar.close for bar in vkospi_history_bars[-_VKOSPI_AVG_WINDOW:]]

    previous_rows = await market_regime_repo.get_recent(
        before_date=as_of_date, limit=_REGIME_HYSTERESIS_LOOKBACK
    )
    previous_regime = previous_rows[0].regime if previous_rows else None
    previous_raw_normal = [bool(row.signals.get("raw_normal", False)) for row in previous_rows]

    regime, regime_signals = judge_regime(
        kospi_close=kospi_close,
        kospi_ma200=kospi_ma200,
        vkospi=vkospi,
        kospi_volatility_20d=kospi_volatility_20d,
        previous_regime=previous_regime,
        previous_raw_normal=previous_raw_normal,
    )
    market_shock, shock_signals = detect_market_shock(
        kospi_prev_close=kospi_prev_close,
        kospi_close=kospi_close,
        vkospi=vkospi,
        vkospi_history_20d=vkospi_history_20d,
    )

    regime_info = MarketRegimeInfo(
        regime_date=as_of_date,
        regime=regime,
        kospi_close=kospi_close,
        kospi_ma200=kospi_ma200,
        vkospi=vkospi,
        kospi_volatility_20d=kospi_volatility_20d,
        market_shock=market_shock,
        signals={**regime_signals, "shock": shock_signals},
    )
    return await market_regime_repo.upsert(regime=regime_info)
