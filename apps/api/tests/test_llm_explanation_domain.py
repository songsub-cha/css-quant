"""Unit tests for ``src.domain.llm_explanation`` (SoT A6.1 stage 5).

Pure DB-free logic — ``AssetScore`` rows constructed directly (no session),
same style as ``test_score_calculation_engine.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from src.domain.ai_score import AssetScore
from src.domain.llm_explanation import (
    build_explanation_prompt,
    compute_cache_key,
    select_explanation_candidates,
    validate_explanation_output,
)
from src.domain.market_regime import RegimeStatus

_AS_OF = date(2026, 8, 16)
_PREVIOUS = date(2026, 8, 15)


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


def test_select_explanation_candidates_filters_below_threshold_delta() -> None:
    unchanged, moved = uuid4(), uuid4()
    today = [
        _score_row(unchanged, score_date=_AS_OF, total_score=Decimal(60)),
        _score_row(moved, score_date=_AS_OF, total_score=Decimal(70)),
    ]
    previous = [
        _score_row(unchanged, score_date=_PREVIOUS, total_score=Decimal(61)),  # |Δ|=1 < 5
        _score_row(moved, score_date=_PREVIOUS, total_score=Decimal(60)),  # |Δ|=10 >= 5
    ]

    selected, skipped = select_explanation_candidates(
        today_scores=today, previous_scores=previous, daily_call_limit=10
    )

    assert {c.asset_id for c in selected} == {moved}
    assert skipped == []


def test_select_explanation_candidates_includes_new_entrants() -> None:
    new_entrant = uuid4()
    today = [_score_row(new_entrant, score_date=_AS_OF, total_score=Decimal(55))]

    selected, skipped = select_explanation_candidates(
        today_scores=today, previous_scores=[], daily_call_limit=10
    )

    assert len(selected) == 1
    assert selected[0].asset_id == new_entrant
    assert selected[0].previous_total_score is None
    assert selected[0].score_delta is None
    assert skipped == []


def test_select_explanation_candidates_sorts_by_magnitude_desc_then_asset_id_asc() -> None:
    small, big, tie_a, tie_b = uuid4(), uuid4(), uuid4(), uuid4()
    tie_low, tie_high = sorted([tie_a, tie_b], key=str)
    today = [
        _score_row(small, score_date=_AS_OF, total_score=Decimal(55)),  # |Δ|=5
        _score_row(big, score_date=_AS_OF, total_score=Decimal(90)),  # |Δ|=40
        _score_row(tie_low, score_date=_AS_OF, total_score=Decimal(60)),  # |Δ|=10
        _score_row(tie_high, score_date=_AS_OF, total_score=Decimal(60)),  # |Δ|=10
    ]
    previous = [
        _score_row(small, score_date=_PREVIOUS, total_score=Decimal(50)),
        _score_row(big, score_date=_PREVIOUS, total_score=Decimal(50)),
        _score_row(tie_low, score_date=_PREVIOUS, total_score=Decimal(50)),
        _score_row(tie_high, score_date=_PREVIOUS, total_score=Decimal(50)),
    ]

    selected, _ = select_explanation_candidates(
        today_scores=today, previous_scores=previous, daily_call_limit=10
    )

    assert [c.asset_id for c in selected] == [big, tie_low, tie_high, small]


def test_select_explanation_candidates_splits_off_over_limit_as_skipped() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    today = [
        _score_row(a, score_date=_AS_OF, total_score=Decimal(90)),  # |Δ|=40
        _score_row(b, score_date=_AS_OF, total_score=Decimal(70)),  # |Δ|=20
        _score_row(c, score_date=_AS_OF, total_score=Decimal(60)),  # |Δ|=10
    ]
    previous = [
        _score_row(a, score_date=_PREVIOUS, total_score=Decimal(50)),
        _score_row(b, score_date=_PREVIOUS, total_score=Decimal(50)),
        _score_row(c, score_date=_PREVIOUS, total_score=Decimal(50)),
    ]

    selected, skipped = select_explanation_candidates(
        today_scores=today, previous_scores=previous, daily_call_limit=2
    )

    assert [cand.asset_id for cand in selected] == [a, b]
    assert skipped == [c]


def test_validate_explanation_output_accepts_well_formed_json() -> None:
    raw = (
        '{"summary": "지표가 개선되었습니다.", '
        '"positive_reasons": ["흐름이 좋습니다"], '
        '"risk_reasons": ["변동성에 유의하세요"]}'
    )

    result = validate_explanation_output(raw)

    assert result is not None
    assert result.summary == "지표가 개선되었습니다."
    assert result.positive_reasons == ["흐름이 좋습니다"]
    assert result.risk_reasons == ["변동성에 유의하세요"]


def test_validate_explanation_output_rejects_forbidden_word() -> None:
    raw = '{"summary": "이 종목은 매력적입니다 (BUY).", "positive_reasons": [], "risk_reasons": []}'

    assert validate_explanation_output(raw) is None


def test_validate_explanation_output_rejects_buy_sell_korean_words() -> None:
    raw = '{"summary": "최근 매수세가 강합니다.", "positive_reasons": [], "risk_reasons": []}'

    assert validate_explanation_output(raw) is None

    raw_sell = '{"summary": "최근 매도세가 강합니다.", "positive_reasons": [], "risk_reasons": []}'

    assert validate_explanation_output(raw_sell) is None


def test_validate_explanation_output_rejects_too_many_reasons() -> None:
    raw = (
        '{"summary": "요약", "positive_reasons": ["a", "b", "c", "d"], "risk_reasons": []}'
    )

    assert validate_explanation_output(raw) is None


def test_validate_explanation_output_rejects_empty_summary() -> None:
    raw = '{"summary": "", "positive_reasons": [], "risk_reasons": []}'

    assert validate_explanation_output(raw) is None


def test_validate_explanation_output_rejects_invalid_json() -> None:
    assert validate_explanation_output("this is not json") is None


def test_build_explanation_prompt_embeds_scores_and_constraints() -> None:
    candidate = select_explanation_candidates(
        today_scores=[_score_row(uuid4(), score_date=_AS_OF, total_score=Decimal(70))],
        previous_scores=[],
        daily_call_limit=10,
    )[0][0]

    prompt = build_explanation_prompt(candidate)

    assert "BUY" in prompt  # 금지어 지시문에 언급되어야 함
    assert str(candidate.total_score) in prompt
    assert "신규 편입" in prompt


def test_compute_cache_key_is_deterministic_and_input_sensitive() -> None:
    candidate_a = select_explanation_candidates(
        today_scores=[_score_row(uuid4(), score_date=_AS_OF, total_score=Decimal(70))],
        previous_scores=[],
        daily_call_limit=10,
    )[0][0]
    candidate_b = candidate_a.model_copy(update={"total_score": Decimal(71)})

    assert compute_cache_key(candidate_a) == compute_cache_key(candidate_a)
    assert compute_cache_key(candidate_a) != compute_cache_key(candidate_b)
