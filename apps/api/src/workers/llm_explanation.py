"""LLM explanation orchestration (SoT A6.1 stage 5 — workers).

Same layer-contract rationale as ``src.workers.tasks``: recording a run in
``job_runs`` needs ``src.services.job_run.run_locked_job``, and calling
``src.adapters.trading_calendar.get_krx_trading_days`` needs an adapter —
neither is reachable from ``src.services`` (its ``forbidden_modules``
excludes reaching back into ``src.workers``, and this module's caller,
``AssetScoreRepository``, is a ``src.domain`` port implemented by an
adapter), so this orchestration lives in ``src.workers``, called directly
(unlike ``sync_asset_master_task``/``collect_prices_task`` in
``src.workers.tasks``, which wrap a ``src.services`` function) — matching
issue #64's plan.

Registering ``generate_llm_explanations`` as an actual Arq cron job is issue
#39's scope — this module only provides the callable pipeline: fetch today's
and the previous trading day's ``ai_scores`` rows -> select candidates
(``src.domain.llm_explanation.select_explanation_candidates``) -> for each,
check the cache, else call the LLM adapter and validate (one retry, then
discard) subject to a running cost budget -> re-upsert only the LLM columns
-> record the run in ``job_runs``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.adapters.llm import LLMClient
from src.adapters.trading_calendar import get_krx_trading_days
from src.domain.ai_score import AssetScore, AssetScoreInfo, AssetScoreRepository
from src.domain.job_run import JobLock, JobRun, JobRunRepository
from src.domain.llm_explanation import (
    CACHE_TTL_SECONDS,
    ESTIMATED_COST_PER_CALL_USD,
    LLMExplanationCache,
    LLMExplanationInput,
    LLMExplanationResult,
    build_explanation_prompt,
    compute_cache_key,
    select_explanation_candidates,
    validate_explanation_output,
)
from src.services.job_run import run_locked_job

# KRX 최장 연휴(설/추석)보다 넉넉한 조회 윈도 — 이 안에서 전 거래일을 찾지
# 못하면(진짜 콜드 스타트) 전일 점수를 빈 리스트로 취급한다.
_LOOKBACK_DAYS = 14

# 검증 실패 시 1회 재시도 후 폐기 (SoT A6.1 5).
_MAX_ATTEMPTS = 2


def _previous_trading_day(as_of_date: date, *, lookback_days: int = _LOOKBACK_DAYS) -> date | None:
    """Return the KRX trading day immediately before ``as_of_date``, or ``None``.

    Deliberately *not* ``as_of_date - timedelta(days=1)``: a bare calendar
    subtraction lands on a weekend/holiday around long weekends and
    KRX-specific holidays (설/추석), which would return an empty score set
    and mark every asset a false "new entrant" — see issue #64's plan
    (code-critic change request) and ``src.workers.backfill_cli``'s use of
    the same calendar for the same reason.
    """
    sessions = get_krx_trading_days(as_of_date - timedelta(days=lookback_days), as_of_date)
    earlier = [d for d in sessions if d < as_of_date]
    return max(earlier) if earlier else None


async def _call_and_validate(
    llm_client: LLMClient, candidate: LLMExplanationInput
) -> LLMExplanationResult | None:
    prompt = build_explanation_prompt(candidate)
    for _ in range(_MAX_ATTEMPTS):
        raw = await llm_client.complete(prompt)
        result = validate_explanation_output(raw)
        if result is not None:
            return result
    return None


async def generate_llm_explanations(
    asset_score_repo: AssetScoreRepository,
    llm_client: LLMClient,
    cache: LLMExplanationCache,
    job_run_repo: JobRunRepository,
    lock: JobLock,
    *,
    as_of_date: date,
    daily_call_limit: int,
    daily_usd_limit: Decimal,
    llm_model: str,
    lock_ttl_seconds: int,
) -> JobRun | None:
    """Generate and persist LLM explanations for ``as_of_date``'s scored assets.

    Returns ``None`` (no ``job_runs`` row) if another run already holds the
    ``(job_name, as_of_date)`` lock — see ``run_locked_job``. Never raises
    for a single asset's LLM failure; only an unexpected error in the
    surrounding orchestration fails the whole run (recorded FAILED by
    ``run_locked_job``, same fail-closed shape every other stage uses).
    """

    async def _work() -> dict[str, Any]:
        today_scores = await asset_score_repo.get_by_date(score_date=as_of_date)
        if not today_scores:
            return {
                "candidates": 0,
                "skipped_over_call_limit": 0,
                "generated": 0,
                "discarded_invalid": 0,
                "cache_hits": 0,
                "skipped_over_budget": 0,
                "budget_exceeded": False,
                "estimated_cost_usd": "0",
            }

        previous_day = _previous_trading_day(as_of_date)
        previous_scores: Sequence[AssetScore] = (
            await asset_score_repo.get_by_date(score_date=previous_day)
            if previous_day is not None
            else []
        )

        candidates, skipped_over_limit = select_explanation_candidates(
            today_scores=today_scores,
            previous_scores=previous_scores,
            daily_call_limit=daily_call_limit,
        )

        by_asset = {s.asset_id: s for s in today_scores}
        generated = 0
        discarded_invalid = 0
        cache_hits = 0
        skipped_over_budget = 0
        budget_exceeded = False
        running_cost = Decimal(0)

        for candidate in candidates:
            cache_key = compute_cache_key(candidate)
            result = await cache.get(cache_key)
            if result is not None:
                cache_hits += 1
            else:
                if running_cost + ESTIMATED_COST_PER_CALL_USD > daily_usd_limit:
                    budget_exceeded = True
                    skipped_over_budget += 1
                    continue
                running_cost += ESTIMATED_COST_PER_CALL_USD
                result = await _call_and_validate(llm_client, candidate)
                if result is None:
                    discarded_invalid += 1
                    continue
                await cache.set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)

            score_row = by_asset[candidate.asset_id]
            await asset_score_repo.upsert(
                score=AssetScoreInfo(
                    asset_id=score_row.asset_id,
                    score_date=score_row.score_date,
                    regime=score_row.regime,
                    total_score=score_row.total_score,
                    momentum_score=score_row.momentum_score,
                    quality_score=score_row.quality_score,
                    value_score=score_row.value_score,
                    liquidity_score=score_row.liquidity_score,
                    risk_score=score_row.risk_score,
                    summary=result.summary,
                    positive_reasons=result.positive_reasons,
                    risk_reasons=result.risk_reasons,
                    llm_model=llm_model,
                    llm_generated_at=datetime.now(UTC),
                )
            )
            generated += 1

        return {
            "candidates": len(candidates),
            "skipped_over_call_limit": len(skipped_over_limit),
            "generated": generated,
            "discarded_invalid": discarded_invalid,
            "cache_hits": cache_hits,
            "skipped_over_budget": skipped_over_budget,
            "budget_exceeded": budget_exceeded,
            "estimated_cost_usd": str(running_cost),
        }

    return await run_locked_job(
        job_run_repo,
        lock,
        job_name="generate_llm_explanations",
        run_date=as_of_date,
        lock_ttl_seconds=lock_ttl_seconds,
        work=_work,
    )
