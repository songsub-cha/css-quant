"""Data quality gate orchestration (SoT A6.4 — workers).

The lint-imports layer contract puts this here rather than in
``src/services``: ``src.services``' ``forbidden_modules`` includes
``src.engine`` (``apps/api/pyproject.toml``), so an orchestrator that calls
``src.engine.quality_gate.judge_quality_gate``'s pure judgement cannot live
in services. ``src.workers``' contract only forbids ``src.api``, so this
module is the legal home — matching ``src.workers.market_regime_detection``
(issue #54) and ``src.workers.universe_filter`` (issue #56).

Unlike those two, this orchestrator also drives ``job_runs`` bookkeeping —
through ``src.services.job_run.start_job_run``/``finish_job_run`` (never the
repository's ``start``/``finish`` directly), the first real caller of that
service wrapper. ``src.services.job_run``'s docstring names
``finish_job_run``'s rejection of ``RUNNING`` as a terminal status as its
one enforced business rule; bypassing the wrapper would leave that rule
unexercised by any caller.

Registering ``evaluate_quality_gate`` as an actual Arq cron job, and having
score-calculation/signal-generation actually consult its result before
running, are issue #39's scope — this module only provides the callable
pipeline: build the candidate pool -> fetch today's/yesterday's price checks
-> fetch today's market regime -> judge -> record to ``job_runs``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from src.adapters.trading_calendar import get_krx_trading_days
from src.domain.asset import AssetRepository, AssetType, Market
from src.domain.job_run import JobRunRepository, JobRunStatus
from src.domain.market_price import MarketPriceRepository
from src.domain.market_regime import MarketRegimeRepository
from src.domain.quality_gate import QualityGateResult, QualityGateThresholds
from src.engine.quality_gate import judge_quality_gate
from src.services.job_run import finish_job_run, start_job_run

_JOB_NAME = "quality_gate"

# How far back to search for the previous trading day feeding the ±30% move
# check's baseline — generous enough to cross any holiday cluster (Lunar New
# Year/Chuseok are the longest KRX closures, well under 14 calendar days).
_PREVIOUS_SESSION_LOOKBACK_DAYS = 14


def _previous_trading_day(as_of_date: date) -> date | None:
    """The most recent KRX session strictly before ``as_of_date``, or ``None``.

    ``None`` means no prior session was found in the lookback window (should
    not happen in practice) — the caller degrades to an empty ``prev_closes``
    map, which skips only the ±30% move leg of the integrity check (see
    ``src.engine.quality_gate._check_integrity``), not the whole gate.
    """
    sessions = get_krx_trading_days(
        as_of_date - timedelta(days=_PREVIOUS_SESSION_LOOKBACK_DAYS), as_of_date
    )
    prior_sessions = [d for d in sessions if d < as_of_date]
    return max(prior_sessions) if prior_sessions else None


async def evaluate_quality_gate(
    asset_repo: AssetRepository,
    market_price_repo: MarketPriceRepository,
    market_regime_repo: MarketRegimeRepository,
    job_run_repo: JobRunRepository,
    *,
    as_of_date: date,
    thresholds: QualityGateThresholds,
) -> QualityGateResult:
    """Fetch, judge, and record one trading day's SoT A6.4 quality gate verdict.

    The candidate-pool denominator for coverage is
    ``asset_repo.list_active(Market.KR, AssetType.STOCK)`` — the filter-
    *before* pool, not ``evaluate_universe``'s filtered result — so an asset
    excluded from the universe solely because its market-cap/trading-value
    data is missing still counts against coverage instead of silently
    shrinking the denominator (SoT A2 원칙 8; see
    ``src.engine.quality_gate._check_coverage``'s docstring).

    No exception handling around the judge/record steps: a crash here
    surfaces directly rather than being swallowed into a FAILED row — the
    same crash-unsafe shape ``detect_market_regime`` has today. Crash-safety
    (catching and recording, cleaning up an orphaned RUNNING row) is issue
    #39's scope.
    """
    job_run = await start_job_run(job_run_repo, job_name=_JOB_NAME, run_date=as_of_date)

    assets = await asset_repo.list_active(Market.KR, AssetType.STOCK)
    universe_asset_ids = {asset.id for asset in assets}

    today_bars = await market_price_repo.get_price_checks(trade_date=as_of_date)

    prev_date = _previous_trading_day(as_of_date)
    prev_closes: dict[UUID, Decimal] = {}
    if prev_date is not None:
        prev_bars = await market_price_repo.get_price_checks(trade_date=prev_date)
        prev_closes = {asset_id: bar.close for asset_id, bar in prev_bars.items()}

    regime = await market_regime_repo.get_by_date(regime_date=as_of_date)

    result = judge_quality_gate(
        gate_date=as_of_date,
        universe_asset_ids=universe_asset_ids,
        today_bars=today_bars,
        prev_closes=prev_closes,
        market_regime_exists=regime is not None,
        thresholds=thresholds,
    )

    status = JobRunStatus.SUCCESS if result.passed else JobRunStatus.FAILED
    failed_check_names = [check.name.value for check in result.checks if not check.passed]
    error = f"failed checks: {', '.join(failed_check_names)}" if failed_check_names else None
    stats = {
        "checks": [
            {"name": check.name.value, "passed": check.passed, "details": check.details}
            for check in result.checks
        ]
    }
    await finish_job_run(job_run_repo, job_run.id, status=status, error=error, stats=stats)

    return result
