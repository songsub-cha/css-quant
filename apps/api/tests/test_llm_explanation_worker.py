"""Worker-level orchestration tests for ``generate_llm_explanations`` (SoT A6.1 stage 5).

Exercises ``src.workers.llm_explanation.generate_llm_explanations`` against
``tests/conftest.py``'s in-memory fakes plus local ``_FakeJobRunRepository``/
``_FakeJobLock`` (same reason ``test_job_run_service.py`` keeps those local
rather than in ``conftest.py``: no other test module needs them) — no live
DB, ``asyncio.run`` directly, same convention as
``test_score_calculation_worker.py``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from src.adapters.llm import FakeLLMClient
from src.domain.ai_score import AssetScore, AssetScoreInfo
from src.domain.job_run import JobRun, JobRunStatus
from src.domain.market_regime import RegimeStatus
from src.workers.llm_explanation import _previous_trading_day, generate_llm_explanations

from .conftest import FakeAssetScoreRepository, FakeLLMExplanationCache

# 2026-08-07 (금) -> 2026-08-10 (월): 사이에 주말만 끼어 있고 KRX 휴장일이
# 없는 실제 캘린더 쌍 (exchange_calendars XKRX 실측, 2026-08-17 워커 실행 시점).
_FRIDAY = date(2026, 8, 7)
_MONDAY = date(2026, 8, 10)
_DAILY_CALL_LIMIT = 1000
_DAILY_USD_LIMIT = Decimal(5)
_LOCK_TTL = 60


def _score_row(asset_id: UUID, *, score_date: date, total_score: Decimal) -> AssetScore:
    return AssetScore(
        asset_id=asset_id,
        score_date=score_date,
        regime=RegimeStatus.NORMAL,
        total_score=total_score,
        momentum_score=Decimal(60),
        quality_score=Decimal(55),
        value_score=Decimal(50),
        liquidity_score=Decimal(45),
        risk_score=Decimal(40),
    )


class _FakeJobRunRepository:
    def __init__(self) -> None:
        self.runs: list[JobRun] = []

    async def start(self, *, job_name: str, run_date: date) -> JobRun:
        row = JobRun(
            id=uuid4(),
            job_name=job_name,
            run_date=run_date,
            status=JobRunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        self.runs.append(row)
        return row

    async def finish(
        self,
        job_run_id: UUID,
        *,
        status: JobRunStatus,
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> JobRun:
        row = next(r for r in self.runs if r.id == job_run_id)
        row.status = status
        row.finished_at = datetime.now(UTC)
        row.error = error
        row.stats = stats
        return row


class _FakeJobLock:
    def __init__(self) -> None:
        self._held: dict[str, str] = {}

    async def acquire(self, key: str, *, ttl_seconds: int) -> str | None:
        if key in self._held:
            return None
        token = f"token-{len(self._held)}"
        self._held[key] = token
        return token

    async def release(self, key: str, token: str) -> None:
        if self._held.get(key) == token:
            del self._held[key]


class _CountingLLMClient:
    """Wraps ``FakeLLMClient`` to count ``.complete()`` calls (cache-hit assertions)."""

    def __init__(self) -> None:
        self._inner = FakeLLMClient()
        self.call_count = 0

    async def complete(self, prompt: str) -> str:
        self.call_count += 1
        return await self._inner.complete(prompt)


class _AlwaysForbiddenLLMClient:
    async def complete(self, prompt: str) -> str:
        return json.dumps(
            {"summary": "이 종목은 BUY입니다.", "positive_reasons": [], "risk_reasons": []}
        )


def _run(
    *,
    score_repo: FakeAssetScoreRepository,
    llm_client: Any,
    cache: FakeLLMExplanationCache,
    as_of_date: date,
    daily_call_limit: int = _DAILY_CALL_LIMIT,
    daily_usd_limit: Decimal = _DAILY_USD_LIMIT,
) -> tuple[JobRun | None, _FakeJobRunRepository, _FakeJobLock]:
    job_run_repo = _FakeJobRunRepository()
    lock = _FakeJobLock()

    async def _call() -> JobRun | None:
        return await generate_llm_explanations(
            score_repo,
            llm_client,
            cache,
            job_run_repo,
            lock,
            as_of_date=as_of_date,
            daily_call_limit=daily_call_limit,
            daily_usd_limit=daily_usd_limit,
            llm_model="fake-llm",
            lock_ttl_seconds=_LOCK_TTL,
        )

    result = asyncio.run(_call())
    return result, job_run_repo, lock


def test_previous_trading_day_returns_friday_before_monday() -> None:
    assert _previous_trading_day(_MONDAY) == _FRIDAY


def test_generate_llm_explanations_fills_llm_fields_for_selected_candidates() -> None:
    async def _seed() -> tuple[FakeAssetScoreRepository, UUID]:
        score_repo = FakeAssetScoreRepository()
        asset_id = uuid4()
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_FRIDAY, total_score=Decimal(50)))
        )
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_MONDAY, total_score=Decimal(80)))
        )
        return score_repo, asset_id

    score_repo, asset_id = asyncio.run(_seed())
    llm_client = _CountingLLMClient()
    cache = FakeLLMExplanationCache()

    job_run, _, lock = _run(
        score_repo=score_repo, llm_client=llm_client, cache=cache, as_of_date=_MONDAY
    )

    assert job_run is not None
    assert job_run.status == JobRunStatus.SUCCESS
    assert job_run.stats is not None
    assert job_run.stats["generated"] == 1
    assert job_run.stats["candidates"] == 1
    assert llm_client.call_count == 1
    assert lock._held == {}

    updated = next(s for s in score_repo.scores if s.score_date == _MONDAY)
    assert updated.summary is not None
    assert updated.positive_reasons
    assert updated.llm_model == "fake-llm"
    assert updated.llm_generated_at is not None


def test_generate_llm_explanations_leaves_unselected_assets_null() -> None:
    async def _seed() -> tuple[FakeAssetScoreRepository, UUID]:
        score_repo = FakeAssetScoreRepository()
        unchanged = uuid4()
        await score_repo.upsert(
            score=_row_info(_score_row(unchanged, score_date=_FRIDAY, total_score=Decimal(50)))
        )
        await score_repo.upsert(
            score=_row_info(_score_row(unchanged, score_date=_MONDAY, total_score=Decimal(51)))
        )
        return score_repo, unchanged

    score_repo, unchanged = asyncio.run(_seed())
    llm_client = _CountingLLMClient()

    job_run, _, _ = _run(
        score_repo=score_repo,
        llm_client=llm_client,
        cache=FakeLLMExplanationCache(),
        as_of_date=_MONDAY,
    )

    assert job_run is not None
    assert job_run.stats is not None
    assert job_run.stats["candidates"] == 0
    assert llm_client.call_count == 0
    row = next(s for s in score_repo.scores if s.score_date == _MONDAY and s.asset_id == unchanged)
    assert row.summary is None


def test_weekend_gap_does_not_misclassify_monday_universe_as_all_new_entrants() -> None:
    """Monday's scores must diff against Friday's, not an empty Sunday snapshot.

    A bare ``as_of_date - timedelta(days=1)`` would look up Sunday (no rows,
    weekend) and treat every Monday asset as a new entrant, blowing the
    daily call budget on an ordinary trading day (issue #64 code-critic
    change request).
    """

    async def _seed() -> tuple[FakeAssetScoreRepository, list[UUID]]:
        score_repo = FakeAssetScoreRepository()
        asset_ids = [uuid4() for _ in range(3)]
        for asset_id in asset_ids:
            await score_repo.upsert(
                score=_row_info(_score_row(asset_id, score_date=_FRIDAY, total_score=Decimal(50)))
            )
            # Monday: unchanged score for every asset — none should qualify.
            await score_repo.upsert(
                score=_row_info(_score_row(asset_id, score_date=_MONDAY, total_score=Decimal(50)))
            )
        return score_repo, asset_ids

    score_repo, _asset_ids = asyncio.run(_seed())

    job_run, _, _ = _run(
        score_repo=score_repo,
        llm_client=_CountingLLMClient(),
        cache=FakeLLMExplanationCache(),
        as_of_date=_MONDAY,
    )

    assert job_run is not None
    assert job_run.stats is not None
    assert job_run.stats["candidates"] == 0


def test_reupsert_preserves_score_and_regime_columns() -> None:
    async def _seed() -> tuple[FakeAssetScoreRepository, UUID]:
        score_repo = FakeAssetScoreRepository()
        asset_id = uuid4()
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_FRIDAY, total_score=Decimal(50)))
        )
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_MONDAY, total_score=Decimal(90)))
        )
        return score_repo, asset_id

    score_repo, asset_id = asyncio.run(_seed())
    before = next(s for s in score_repo.scores if s.score_date == _MONDAY)
    before_snapshot = (
        before.regime,
        before.total_score,
        before.momentum_score,
        before.quality_score,
        before.value_score,
        before.liquidity_score,
        before.risk_score,
    )

    _run(
        score_repo=score_repo,
        llm_client=_CountingLLMClient(),
        cache=FakeLLMExplanationCache(),
        as_of_date=_MONDAY,
    )

    after = next(s for s in score_repo.scores if s.score_date == _MONDAY)
    after_snapshot = (
        after.regime,
        after.total_score,
        after.momentum_score,
        after.quality_score,
        after.value_score,
        after.liquidity_score,
        after.risk_score,
    )
    assert after_snapshot == before_snapshot
    assert after.summary is not None


def test_validation_failure_retries_once_then_discards_leaving_fields_null() -> None:
    async def _seed() -> tuple[FakeAssetScoreRepository, UUID]:
        score_repo = FakeAssetScoreRepository()
        asset_id = uuid4()
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_FRIDAY, total_score=Decimal(50)))
        )
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_MONDAY, total_score=Decimal(80)))
        )
        return score_repo, asset_id

    score_repo, asset_id = asyncio.run(_seed())

    job_run, _, _ = _run(
        score_repo=score_repo,
        llm_client=_AlwaysForbiddenLLMClient(),
        cache=FakeLLMExplanationCache(),
        as_of_date=_MONDAY,
    )

    assert job_run is not None
    assert job_run.stats is not None
    assert job_run.stats["discarded_invalid"] == 1
    assert job_run.stats["generated"] == 0
    row = next(s for s in score_repo.scores if s.score_date == _MONDAY)
    assert row.summary is None


def test_cache_hit_skips_llm_call() -> None:
    async def _seed() -> tuple[FakeAssetScoreRepository, UUID]:
        score_repo = FakeAssetScoreRepository()
        asset_id = uuid4()
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_FRIDAY, total_score=Decimal(50)))
        )
        await score_repo.upsert(
            score=_row_info(_score_row(asset_id, score_date=_MONDAY, total_score=Decimal(80)))
        )
        return score_repo, asset_id

    score_repo, _asset_id = asyncio.run(_seed())
    cache = FakeLLMExplanationCache()
    llm_client = _CountingLLMClient()

    _run(score_repo=score_repo, llm_client=llm_client, cache=cache, as_of_date=_MONDAY)
    assert llm_client.call_count == 1
    second_run, _, _ = _run(
        score_repo=score_repo, llm_client=llm_client, cache=cache, as_of_date=_MONDAY
    )

    assert llm_client.call_count == 1  # second run hits the cache, no new adapter call
    assert second_run is not None
    assert second_run.stats is not None
    assert second_run.stats["cache_hits"] == 1


def test_budget_guardrail_skips_calls_once_daily_usd_limit_exceeded() -> None:
    async def _seed() -> FakeAssetScoreRepository:
        score_repo = FakeAssetScoreRepository()
        for _ in range(3):
            asset_id = uuid4()
            await score_repo.upsert(
                score=_row_info(_score_row(asset_id, score_date=_FRIDAY, total_score=Decimal(50)))
            )
            await score_repo.upsert(
                score=_row_info(_score_row(asset_id, score_date=_MONDAY, total_score=Decimal(80)))
            )
        return score_repo

    score_repo = asyncio.run(_seed())
    llm_client = _CountingLLMClient()

    # ESTIMATED_COST_PER_CALL_USD is 0.001 — a budget of 0.0015 affords
    # exactly one call before the second one would exceed it.
    job_run, _, _ = _run(
        score_repo=score_repo,
        llm_client=llm_client,
        cache=FakeLLMExplanationCache(),
        as_of_date=_MONDAY,
        daily_usd_limit=Decimal("0.0015"),
    )

    assert job_run is not None
    assert job_run.stats is not None
    assert job_run.stats["budget_exceeded"] is True
    assert job_run.stats["skipped_over_budget"] == 2
    assert llm_client.call_count == 1


def _row_info(score: AssetScore) -> AssetScoreInfo:
    return AssetScoreInfo(
        asset_id=score.asset_id,
        score_date=score.score_date,
        regime=score.regime,
        total_score=score.total_score,
        momentum_score=score.momentum_score,
        quality_score=score.quality_score,
        value_score=score.value_score,
        liquidity_score=score.liquidity_score,
        risk_score=score.risk_score,
    )
