"""AI-score pipeline schema (SoT A6.1 stages 3/4/6, C3 — domain).

``ai_scores`` is the final stage of the 6-stage AI-score pipeline (SoT A6.1):
universe filter (issue #56/PR #57) -> factor calculation (issue #58/PR #59)
-> **normalization** -> **weighted sum** -> LLM explanation (out of scope,
see issue #62's plan) -> **persistence**. This module adds the table, the
port, the DTO the engine's output gets upserted through, and the weight
DTOs the engine's weighted-sum step consumes — the pure math (winsorizing,
percentile normalization, direction reversal, weighted sum) lives in
``src.engine.score_calculation`` (SoT A2 원칙 7), the orchestration in
``src.workers.score_calculation`` (same fetch-then-upsert split as
``AssetFactorRepository``/``MarketRegimeRepository``).

LLM-authored fields (``summary``/``positive_reasons``/``risk_reasons``/
``llm_model``/``llm_generated_at``) start out ``None`` from this pipeline —
``src.workers.score_calculation.calculate_scores`` never sets them.
SoT A6.1 stage 5 (LLM explanation generation) fills them in a separate pass,
``src.workers.llm_explanation.generate_llm_explanations`` (issue #64), which
re-upserts only those five columns via the same ``AssetScoreRepository.upsert``
port this module defines, preserving the score/regime columns
``calculate_scores`` already wrote (see ``get_by_date`` below, the read side
that pass depends on).

``regime`` reuses ``src.domain.market_regime.RegimeStatus`` rather than a new
enum — the DB column maps to the same ``regime_status`` Postgres type
``market_regimes`` already owns (see the migration's docstring for why the
new migration neither creates nor drops that type).

Wiring an actual caller (Arq cron registration, ``job_runs`` bookkeeping) is
issue #39's scope — this module, plus ``src.engine.score_calculation`` and
``src.workers.score_calculation``, only add the callable pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import Date as SADate
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base
from src.domain.market_regime import RegimeStatus

_REGIME_STATUS_ENUM = SAEnum(
    RegimeStatus, name="regime_status", values_callable=lambda e: [x.value for x in e]
)

_WEIGHT_SUM = Decimal(1)


class MissingRegimeError(Exception):
    """Raised when no ``market_regimes`` row exists for the requested ``score_date``.

    Fail-closed (SoT A2 원칙 8): score calculation must not proceed with a
    guessed or default regime — SoT A6.1 4 requires the regime *actually in
    effect* that day to select the weighted-sum profile, and that same
    regime must be persisted alongside the score for reproducibility.
    """


class FactorWeights(BaseModel):
    """One regime's five factor weights (SoT A6.2 table) — must sum to exactly 1.0."""

    model_config = ConfigDict(frozen=True)

    momentum: Decimal
    quality: Decimal
    value: Decimal
    liquidity: Decimal
    risk: Decimal

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> FactorWeights:
        total = self.momentum + self.quality + self.value + self.liquidity + self.risk
        if total != _WEIGHT_SUM:
            raise ValueError(f"factor weights must sum to 1.0, got {total}")
        return self


class RegimeWeightProfile(BaseModel):
    """Both regimes' weight profiles (SoT A6.2) — one instance covers the whole
    pipeline; ``for_regime`` selects the profile matching a given day's regime.
    """

    model_config = ConfigDict(frozen=True)

    normal: FactorWeights
    defensive: FactorWeights

    def for_regime(self, regime: RegimeStatus) -> FactorWeights:
        return self.normal if regime is RegimeStatus.NORMAL else self.defensive


class AssetScoreInfo(BaseModel):
    """External-facing representation of one asset's one-day score snapshot.

    ``src.workers.score_calculation.calculate_scores`` builds one of these per
    non-held asset from ``src.engine.score_calculation``'s pure output and
    passes it to ``AssetScoreRepository.upsert``. LLM fields are always
    ``None`` — see module docstring.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    score_date: date
    regime: RegimeStatus

    total_score: Decimal
    momentum_score: Decimal
    quality_score: Decimal
    value_score: Decimal
    liquidity_score: Decimal
    risk_score: Decimal

    summary: str | None = None
    positive_reasons: list[str] | None = None
    risk_reasons: list[str] | None = None
    llm_model: str | None = None
    llm_generated_at: datetime | None = None


class AssetScoreRepository(Protocol):
    """Port ``src.workers.score_calculation`` depends on.

    Identity is ``(asset_id, score_date)``, matching ``AssetScore``'s
    composite primary key — like ``AssetFactorRepository``, identity is
    already embedded in the DTO, so ``upsert`` takes only ``score``.
    """

    async def upsert(self, *, score: AssetScoreInfo) -> AssetScore:
        """Update the ``(score.asset_id, score.score_date)`` row if one exists,
        else insert a new one.
        """
        ...

    async def get_by_date(self, *, score_date: date) -> Sequence[AssetScore]:
        """Return every scored asset for ``score_date`` — own-row lookup, no
        calendar arithmetic (that lives in ``src.adapters.trading_calendar``).

        ``src.workers.llm_explanation.generate_llm_explanations`` calls this
        twice: once for the day being explained, once for the previous
        *trading* day (resolved via ``get_krx_trading_days``, not a bare
        ``score_date - 1`` calendar subtraction) to compute each asset's
        score delta.
        """
        ...


class AssetScore(Base):
    """One asset's one-day AI score row (SoT A6.1 stage 6/C3 — ``ai_scores``).

    Identity is ``(asset_id, score_date)`` — one row per scored asset per
    trading day. No row is written for an asset ``src.engine.score_calculation``
    marks on-hold (missing-factor threshold, SoT A6.1 3) — see
    ``src.workers.score_calculation``'s docstring.
    """

    __tablename__ = "ai_scores"

    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    score_date: Mapped[date] = mapped_column(SADate, primary_key=True)

    regime: Mapped[RegimeStatus] = mapped_column(_REGIME_STATUS_ENUM)

    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    momentum_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    quality_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    value_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    liquidity_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    summary: Mapped[str | None] = mapped_column(Text)
    positive_reasons: Mapped[list[Any] | None] = mapped_column(JSONB)
    risk_reasons: Mapped[list[Any] | None] = mapped_column(JSONB)
    llm_model: Mapped[str | None] = mapped_column(String)
    llm_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
