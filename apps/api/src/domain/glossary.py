"""Glossary term schema (SoT A6.12 — domain).

Read-only reference content, not a DB table (SoT A6.12: "DB 테이블 아님").
``apps/api/glossary.ko.yaml`` is the single source; ``src.adapters.glossary``
loads and validates it into a list of these frozen models, cached for the
process lifetime by ``src.api.deps.get_glossary_terms``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GlossaryCategory(StrEnum):
    FACTOR = "factor"
    FINANCIAL_METRIC = "financial_metric"
    PERFORMANCE_METRIC = "performance_metric"
    TRADING_ORDER = "trading_order"
    RISK = "risk"
    DISCLOSURE = "disclosure"
    MARKET_REGIME = "market_regime"


class GlossaryDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NEUTRAL = "neutral"


class GlossaryTerm(BaseModel):
    """One glossary entry (SoT A6.12 item schema)."""

    model_config = ConfigDict(frozen=True)

    key: str
    term_ko: str
    term_en: str
    category: GlossaryCategory
    definition: str
    interpretation: str
    caution: str | None = None
    in_system: str | None = None
    direction: GlossaryDirection | None = None
    related: list[str] = Field(default_factory=list)
