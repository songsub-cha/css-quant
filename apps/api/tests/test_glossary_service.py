"""list_glossary_terms filter tests (SoT A6.12 — pure function, no I/O)."""

from __future__ import annotations

from src.domain.glossary import GlossaryCategory, GlossaryTerm
from src.services.glossary import list_glossary_terms

_PER = GlossaryTerm(
    key="per",
    term_ko="PER",
    term_en="Price-to-Earnings Ratio",
    category=GlossaryCategory.FINANCIAL_METRIC,
    definition="주가를 주당순이익으로 나눈 값.",
    interpretation="낮을수록 저평가.",
)
_MOMENTUM = GlossaryTerm(
    key="momentum_factor",
    term_ko="모멘텀 팩터",
    term_en="Momentum Factor",
    category=GlossaryCategory.FACTOR,
    definition="상승 추세를 측정하는 지표.",
    interpretation="높을수록 상승세가 강함.",
)
_TERMS = [_PER, _MOMENTUM]


def test_no_filters_returns_all_terms() -> None:
    assert list_glossary_terms(_TERMS) == _TERMS


def test_category_filter_narrows_to_matching_category() -> None:
    result = list_glossary_terms(_TERMS, category=GlossaryCategory.FACTOR)

    assert result == [_MOMENTUM]


def test_q_filter_matches_term_en_case_insensitive() -> None:
    result = list_glossary_terms(_TERMS, q="PRICE-TO-EARNINGS")

    assert result == [_PER]


def test_q_filter_matches_definition_substring() -> None:
    result = list_glossary_terms(_TERMS, q="상승 추세")

    assert result == [_MOMENTUM]


def test_category_and_q_filters_combine() -> None:
    result = list_glossary_terms(_TERMS, category=GlossaryCategory.FACTOR, q="per")

    assert result == []


def test_q_filter_with_no_match_returns_empty_list() -> None:
    result = list_glossary_terms(_TERMS, q="존재하지않는용어")

    assert result == []
