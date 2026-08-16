"""LLM explanation candidate selection, prompting, output validation (SoT A6.1 5 — domain).

Pure logic only — no network, no DB. ``src.workers.llm_explanation`` is the
only caller: it fetches today's and the previous trading day's ``ai_scores``
rows, then uses this module to (1) pick which assets get an LLM call
(``select_explanation_candidates``), (2) build the prompt
(``build_explanation_prompt``), (3) validate the raw completion
(``validate_explanation_output``), and (4) compute a cache key
(``compute_cache_key``) so identical inputs skip the adapter call entirely
(``LLMExplanationCache``, implemented by
``src.adapters.llm_cache.RedisLLMExplanationCache``).

``LLMExplanationInput`` is built from ``AssetScore``'s own five normalized
factor scores (momentum/quality/value/liquidity/risk, each already a 0-100
percentile — SoT A6.1 3) rather than the pre-normalization raw indicator
values (``asset_factors``) or a sector average, neither of which this
pipeline fetches. SoT A6.1 5 asks for "raw 팩터/섹터 평균" as prompt input;
wiring those in is a follow-up (this module's DTO would need a
``sector_average_score`` field and the worker would need
``AssetFactorRepository`` plus a sector-classification source, neither of
which exist yet) — noted as a non-blocking gap during issue #64 planning.

Real vendor function calling (OpenAI/Anthropic structured output) is out of
scope (see ``src.adapters.llm`` docstring) — ``build_explanation_prompt``
instead asks the model to return a single JSON object matching this
module's schema as plain text, and ``validate_explanation_output`` parses
that text back.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.domain.ai_score import AssetScore

# SoT A6.1 5: ±5점 이상 변동 또는 신규 편입 종목만 후보로 선별한다.
MIN_SCORE_DELTA = Decimal(5)

# 동일 input 해시 재요청은 캐시로 재호출을 막는다 (SoT A6.1 5) — 7일.
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# 실벤더 어댑터(OpenAI/Anthropic)가 없어 per-call 실측 토큰/비용을 알 수
# 없다 (issue #64 범위 제외 — src.adapters.llm 독스트링 참고). 예산
# 가드레일은 이 상수를 호출 1건의 예상 비용으로 근사해 누적 합산한다.
ESTIMATED_COST_PER_CALL_USD = Decimal("0.001")

_FORBIDDEN_WORDS = ("점수", "등급", "buy", "sell", "매수", "매도")
_MAX_REASONS = 3

# 신규 편입 종목(전일 점수 없음)은 항상 최우선순위로 선별한다 — 변동폭
# 정렬에서 어떤 |Δscore|보다도 앞선다는 뜻으로, 유한한 magnitude(최대
# 100점 만점 척도) 값들보다 확실히 큰 sentinel을 쓴다.
_NEW_ENTRANT_PRIORITY = Decimal(1_000_000)


class LLMExplanationInput(BaseModel):
    """One asset's structured input for an LLM explanation call (SoT A6.1 5).

    ``previous_total_score``/``score_delta`` are ``None`` exactly when the
    asset is a new entrant (absent from the previous trading day's scores).
    """

    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    total_score: Decimal
    momentum_score: Decimal
    quality_score: Decimal
    value_score: Decimal
    liquidity_score: Decimal
    risk_score: Decimal
    previous_total_score: Decimal | None
    score_delta: Decimal | None


class LLMExplanationResult(BaseModel):
    """Validated LLM output — what gets written into ``ai_scores``'s LLM columns."""

    model_config = ConfigDict(frozen=True)

    summary: str
    positive_reasons: list[str]
    risk_reasons: list[str]


class LLMExplanationCache(Protocol):
    """Port ``src.workers.llm_explanation`` depends on.

    ``src.adapters.llm_cache.RedisLLMExplanationCache`` implements this.
    """

    async def get(self, key: str) -> LLMExplanationResult | None: ...

    async def set(self, key: str, result: LLMExplanationResult, *, ttl_seconds: int) -> None: ...


def select_explanation_candidates(
    *,
    today_scores: Sequence[AssetScore],
    previous_scores: Sequence[AssetScore],
    daily_call_limit: int,
) -> tuple[list[LLMExplanationInput], list[UUID]]:
    """Pick which of ``today_scores`` get an LLM call.

    Filters to ``|score_delta| >= MIN_SCORE_DELTA`` or new entrants (no
    matching ``previous_scores`` row — ``previous_scores`` may legitimately
    be empty, e.g. cold start), then sorts by priority descending (new
    entrants first, then |score_delta| descending, ties broken by
    ``asset_id`` ascending — ``AssetScore`` carries no ticker string, so
    ``asset_id`` is the closest stable, deterministic tie-break key
    available to this pure function).

    Returns ``(selected, skipped_over_limit)`` — ``selected`` is capped at
    ``daily_call_limit``; everything past that cap is returned as
    ``skipped_over_limit`` (asset IDs only) rather than dropped silently.
    """
    previous_by_asset = {s.asset_id: s.total_score for s in previous_scores}

    ranked: list[tuple[Decimal, LLMExplanationInput]] = []
    for score in today_scores:
        previous_total = previous_by_asset.get(score.asset_id)
        if previous_total is None:
            priority = _NEW_ENTRANT_PRIORITY
            delta = None
        else:
            delta = score.total_score - previous_total
            magnitude = abs(delta)
            if magnitude < MIN_SCORE_DELTA:
                continue
            priority = magnitude

        ranked.append(
            (
                priority,
                LLMExplanationInput(
                    asset_id=score.asset_id,
                    total_score=score.total_score,
                    momentum_score=score.momentum_score,
                    quality_score=score.quality_score,
                    value_score=score.value_score,
                    liquidity_score=score.liquidity_score,
                    risk_score=score.risk_score,
                    previous_total_score=previous_total,
                    score_delta=delta,
                ),
            )
        )

    ranked.sort(key=lambda pair: (-pair[0], str(pair[1].asset_id)))

    selected = [candidate for _, candidate in ranked[:daily_call_limit]]
    skipped_over_limit = [candidate.asset_id for _, candidate in ranked[daily_call_limit:]]
    return selected, skipped_over_limit


def build_explanation_prompt(candidate: LLMExplanationInput) -> str:
    """Build the full (system + structured input) prompt text for one candidate.

    Constraints baked into the prompt text itself (SoT A6.1 5 — no
    real function-calling schema enforcement, see module docstring):
    Korean only, never use the words 점수/등급/BUY/SELL/매수/매도, never invent
    a number not present in the input below, no buy/sell/hold action
    recommendations, and explain any jargon in plain language on first use
    (SoT A6.12). The model must reply with exactly one JSON object with keys
    ``summary`` (1-2 sentences), ``positive_reasons`` (<=3 items),
    ``risk_reasons`` (<=3 items) — no prose outside the JSON.
    """
    if candidate.score_delta is None:
        delta_text = "신규 편입 (전일 비교 없음)"
    else:
        delta_text = str(candidate.score_delta)
    return (
        "당신은 주식 투자 초보자를 위한 설명가입니다. 아래 지표만 근거로 삼아 한국어로 "
        "설명을 작성하세요. 다음 단어는 절대 사용하지 마세요: 점수, 등급, BUY, SELL, 매수, 매도. "
        "아래에 주어지지 않은 새로운 숫자를 만들어내지 마세요. 매수/매도/보유 등 행동을 "
        "추천하지 마세요. 전문용어를 처음 쓸 때는 괄호 안에 짧은 풀어쓰기를 덧붙이세요.\n\n"
        f"자산 ID: {candidate.asset_id}\n"
        f"종합 점수: {candidate.total_score}\n"
        f"전일 대비 변동: {delta_text}\n"
        f"모멘텀 지표: {candidate.momentum_score}\n"
        f"퀄리티 지표: {candidate.quality_score}\n"
        f"밸류 지표: {candidate.value_score}\n"
        f"유동성 지표: {candidate.liquidity_score}\n"
        f"리스크 지표: {candidate.risk_score}\n\n"
        '다음 JSON 스키마로만 응답하세요(다른 텍스트 금지): '
        '{"summary": "1~2문장", "positive_reasons": ["문장", ...최대 3개], '
        '"risk_reasons": ["문장", ...최대 3개]}'
    )


def validate_explanation_output(raw: str) -> LLMExplanationResult | None:
    """Parse+validate a raw completion; ``None`` means "discard, retry once, then give up".

    Rejects: invalid JSON / missing keys, a forbidden word anywhere in
    ``summary``/``positive_reasons``/``risk_reasons`` (case-insensitive),
    more than ``_MAX_REASONS`` items in either reasons list, or an empty
    ``summary``.
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    summary = payload.get("summary")
    positive_reasons = payload.get("positive_reasons")
    risk_reasons = payload.get("risk_reasons")

    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(positive_reasons, list) or not all(
        isinstance(r, str) for r in positive_reasons
    ):
        return None
    if not isinstance(risk_reasons, list) or not all(isinstance(r, str) for r in risk_reasons):
        return None
    if len(positive_reasons) > _MAX_REASONS or len(risk_reasons) > _MAX_REASONS:
        return None

    haystack = " ".join([summary, *positive_reasons, *risk_reasons]).lower()
    if any(word.lower() in haystack for word in _FORBIDDEN_WORDS):
        return None

    return LLMExplanationResult(
        summary=summary, positive_reasons=positive_reasons, risk_reasons=risk_reasons
    )


def compute_cache_key(candidate: LLMExplanationInput) -> str:
    """Deterministic cache key for ``candidate`` — same structured input, same key."""
    payload = candidate.model_dump_json()
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"llm_explanation:{digest}"
