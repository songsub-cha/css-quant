"""Worker-level orchestration tests for ``evaluate_quality_gate`` (SoT A6.4).

Exercises ``src.workers.quality_gate.evaluate_quality_gate`` against
``tests/conftest.py``'s in-memory fakes — no live DB, same shape as
``test_universe_filter_worker.py``/``test_market_regime_detection.py``.

``_AS_OF``/``_PREV`` are real XKRX trading days (verified against
``exchange_calendars`` directly) since ``_previous_trading_day`` calls the
real ``src.adapters.trading_calendar.get_krx_trading_days`` — same
direct-adapter-import shape as ``src.workers.backfill_cli``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.domain.asset import AssetType, Exchange, Market
from src.domain.job_run import JobRun, JobRunStatus
from src.domain.market_price import DailyPriceInfo
from src.domain.market_regime import MarketRegimeInfo, RegimeStatus
from src.domain.quality_gate import QualityCheckName, QualityGateThresholds
from src.workers.quality_gate import evaluate_quality_gate

from .conftest import (
    FakeAssetRepository,
    FakeJobRunRepository,
    FakeMarketPriceRepository,
    FakeMarketRegimeRepository,
)

_AS_OF = date(2026, 8, 7)
_PREV = date(2026, 8, 6)
_THRESHOLDS = QualityGateThresholds(
    coverage_min_pct=Decimal("0.98"), max_price_move_pct=Decimal("0.30")
)


class _SpyJobRunRepository(FakeJobRunRepository):
    """Wraps ``FakeJobRunRepository`` to assert ``finish`` is never called with RUNNING.

    Regression guard for the plan's requirement that ``job_runs`` bookkeeping
    routes through ``src.services.job_run.start_job_run``/``finish_job_run``
    (never ``job_run_repo.start``/``finish`` directly) — the wrapper's one
    enforced rule is exactly this rejection (SoT: ``src/services/job_run.py``
    docstring).
    """

    def __init__(self) -> None:
        super().__init__()
        self.finish_statuses: list[JobRunStatus] = []

    async def finish(
        self,
        job_run_id: UUID,
        *,
        status: JobRunStatus,
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> JobRun:
        assert status != JobRunStatus.RUNNING, (
            "finish must never observe RUNNING — proves the terminal-status"
            " guard in src.services.job_run.finish_job_run is actually wired"
            " into evaluate_quality_gate's call path"
        )
        self.finish_statuses.append(status)
        return await super().finish(job_run_id, status=status, error=error, stats=stats)


def _bar(ticker: str, trade_date: date, *, close: int = 100) -> DailyPriceInfo:
    return DailyPriceInfo(
        ticker=ticker,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        adjusted_close=Decimal(close),
        volume=1,
        trading_value=Decimal(close),
    )


def _regime_info(regime_date: date) -> MarketRegimeInfo:
    return MarketRegimeInfo(
        regime_date=regime_date,
        regime=RegimeStatus.NORMAL,
        kospi_close=Decimal("2665.12"),
        kospi_ma200=Decimal("2600.56"),
        vkospi=Decimal("18.5"),
        kospi_volatility_20d=Decimal("0.0123"),
        market_shock=False,
        signals={"raw_normal": True},
    )


async def _seed_asset(asset_repo: FakeAssetRepository, ticker: str) -> UUID:
    asset = await asset_repo.upsert_active(
        ticker=ticker,
        name=f"asset-{ticker}",
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )
    return asset.id


def test_evaluate_quality_gate_records_success_job_run_when_gate_passes() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        regime_repo = FakeMarketRegimeRepository()
        job_run_repo = _SpyJobRunRepository()

        for i in range(5):
            ticker = f"00{i}"
            asset_id = await _seed_asset(asset_repo, ticker)
            await price_repo.upsert(asset_id=asset_id, bar=_bar(ticker, _AS_OF))
        await regime_repo.upsert(regime=_regime_info(_AS_OF))

        result = await evaluate_quality_gate(
            asset_repo, price_repo, regime_repo, job_run_repo, as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        assert result.passed is True
        assert len(job_run_repo.runs) == 1
        assert job_run_repo.runs[0].status == JobRunStatus.SUCCESS
        assert job_run_repo.runs[0].stats is not None
        assert job_run_repo.runs[0].finished_at is not None
        assert job_run_repo.finish_statuses == [JobRunStatus.SUCCESS]

    asyncio.run(_run())


def test_evaluate_quality_gate_records_failed_job_run_when_gate_fails() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        regime_repo = FakeMarketRegimeRepository()  # no regime row seeded -> INDICATOR fails
        job_run_repo = _SpyJobRunRepository()

        asset_id = await _seed_asset(asset_repo, "005930")
        await price_repo.upsert(asset_id=asset_id, bar=_bar("005930", _AS_OF))

        result = await evaluate_quality_gate(
            asset_repo, price_repo, regime_repo, job_run_repo, as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        assert result.passed is False
        assert len(job_run_repo.runs) == 1
        assert job_run_repo.runs[0].status == JobRunStatus.FAILED
        assert job_run_repo.runs[0].error is not None
        assert "INDICATOR" in job_run_repo.runs[0].error
        assert job_run_repo.finish_statuses == [JobRunStatus.FAILED]

    asyncio.run(_run())


def test_evaluate_quality_gate_coverage_denominator_is_unfiltered_active_pool() -> None:
    """Regression guard: the coverage denominator must be every active KR STOCK
    asset (``asset_repo.list_active``), not ``evaluate_universe``'s filtered
    result. An asset entirely missing market_prices data (which would also
    make it fail ``evaluate_universe`` on missing market-cap/trading-value
    grounds) must still count against the denominator, not vanish from it —
    a vanished-from-denominator asset would silently inflate coverage% and
    hide a real data gap (SoT A2 원칙 8, fail-open prevention)."""

    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        regime_repo = FakeMarketRegimeRepository()
        job_run_repo = _SpyJobRunRepository()

        for i in range(19):
            ticker = f"{i:06d}"
            asset_id = await _seed_asset(asset_repo, ticker)
            await price_repo.upsert(asset_id=asset_id, bar=_bar(ticker, _AS_OF))
        # 20th asset has NO market_prices row at all, ever — no bar, no
        # market cap, no trading value. evaluate_universe would exclude it
        # (MARKET_CAP_DATA_MISSING/AVG_TRADING_VALUE_DATA_MISSING), but it
        # must still count in the quality gate's denominator.
        await _seed_asset(asset_repo, "999999")
        await regime_repo.upsert(regime=_regime_info(_AS_OF))

        result = await evaluate_quality_gate(
            asset_repo, price_repo, regime_repo, job_run_repo, as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        coverage = next(c for c in result.checks if c.name == QualityCheckName.COVERAGE)
        assert coverage.details["universe_count"] == 20
        assert coverage.details["covered_count"] == 19
        assert coverage.details["coverage_pct"] == 0.95
        assert coverage.passed is False  # 95% < 98% threshold
        assert result.passed is False

    asyncio.run(_run())


def test_evaluate_quality_gate_fetches_prior_session_closes_for_move_check() -> None:
    """``_previous_trading_day`` resolves to the real prior XKRX session
    (2026-08-06 for 2026-08-07), and that session's closes feed the ±30%
    integrity leg."""

    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        regime_repo = FakeMarketRegimeRepository()
        job_run_repo = _SpyJobRunRepository()

        asset_id = await _seed_asset(asset_repo, "005930")
        await price_repo.upsert(asset_id=asset_id, bar=_bar("005930", _PREV, close=100))
        # +40% vs. yesterday's close -> exceeds the 30% threshold.
        await price_repo.upsert(asset_id=asset_id, bar=_bar("005930", _AS_OF, close=140))
        await regime_repo.upsert(regime=_regime_info(_AS_OF))

        result = await evaluate_quality_gate(
            asset_repo, price_repo, regime_repo, job_run_repo, as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        integrity = next(c for c in result.checks if c.name == QualityCheckName.INTEGRITY)
        assert integrity.passed is False
        assert integrity.details["reason_counts"] == {"price_move_exceeds_threshold": 1}
        assert result.passed is False

    asyncio.run(_run())
