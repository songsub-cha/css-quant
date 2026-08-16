"""AI-score pipeline factor schema (SoT A6.1 stage 2/C3 — domain).

``asset_factors`` is the second stage of the 6-stage AI-score pipeline (SoT
A6.1): universe filter (issue #56/PR #57) -> **factor calculation** ->
normalization -> weighted sum -> LLM explanation -> persistence. This module
only adds the table, the port, and the DTO the raw per-asset factor values
(Momentum/Quality/Value/Liquidity/Risk) get upserted through — the pure math
lives in ``src.engine.factor_calculation`` (SoT A2 원칙 7), the orchestration
in ``src.workers.factor_calculation`` (same fetch-then-upsert split as
``IndexPriceRepository``/``MarketRegimeRepository``).

Every factor field is independently nullable: a field is ``None`` when its
own inputs are insufficient (short price history for a newly listed stock,
fewer than 4 disclosed quarters for TTM, a non-positive denominator for a
ratio) — never a stand-in "0" that a later percentile-normalization stage
could misread as a real value. See ``src.engine.factor_calculation``'s
module docstring for each field's exact insufficiency rule.

``market_cap``/``is_managed``/``is_alert`` are a universe-evaluation-time
snapshot (SoT A6.1 stage 1's inputs), carried alongside the factors rather
than re-derived later — the same values ``src.workers.universe_filter``
would have computed for this ``(asset_id, factor_date)``, persisted here so
a later pipeline stage never needs to re-query ``market_prices``/``assets``
for them. ``financial_data_as_of`` is observational only (the most recent
disclosed quarter TTM drew from) — it is not what enforces the SoT A6.7.2
look-ahead bound; that bound is structural, enforced by
``FinancialStatementRepository.get_statement_history``'s
``disclosed_at <= as_of_date`` query filter.

Wiring an actual caller (Arq cron registration, ``job_runs`` bookkeeping) is
issue #39's scope — this module, plus ``src.engine.factor_calculation`` and
``src.workers.factor_calculation``, only add the callable pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class AssetFactorInfo(BaseModel):
    """External-facing representation of one asset's one-day factor snapshot.

    ``src.workers.factor_calculation.calculate_factors`` builds one of these
    per included universe asset per ``as_of_date`` from
    ``src.engine.factor_calculation``'s pure output and passes it to
    ``AssetFactorRepository.upsert``.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    factor_date: date

    # Momentum (SoT A6.1)
    momentum_3m: Decimal | None
    momentum_6m: Decimal | None
    dist_52w_high: Decimal | None
    ma20_deviation: Decimal | None

    # Quality (SoT A6.1) — TTM-derived, disclosed-at bounded
    roe: Decimal | None
    op_margin: Decimal | None
    revenue_growth_yoy: Decimal | None
    debt_ratio: Decimal | None

    # Value (SoT A6.1) — EV/EBITDA deliberately excluded (see issue #58 plan)
    per: Decimal | None
    pbr: Decimal | None

    # Liquidity (SoT A6.1)
    avg_trading_value_20d: Decimal | None
    volume_cv: Decimal | None

    # Risk (SoT A6.1)
    volatility_60d: Decimal | None
    mdd_60d: Decimal | None
    gap_frequency_60d: Decimal | None

    # Universe-evaluation-time snapshot (SoT A6.1 stage 1)
    market_cap: Decimal | None
    is_managed: bool
    is_alert: bool

    # Observational only — see module docstring.
    financial_data_as_of: date | None


class AssetFactorRepository(Protocol):
    """Port ``src.workers.factor_calculation`` depends on.

    Identity is ``(asset_id, factor_date)``, matching ``AssetFactor``'s
    composite primary key — like ``IndexPriceRepository``, identity is
    already embedded in the DTO, so ``upsert`` takes only ``factor``.
    """

    async def upsert(self, *, factor: AssetFactorInfo) -> AssetFactor:
        """Update the ``(factor.asset_id, factor.factor_date)`` row if one exists,
        else insert a new one.
        """
        ...


class AssetFactor(Base):
    """One asset's one-day raw factor snapshot (SoT A6.1/C3 — asset_factors).

    Identity is ``(asset_id, factor_date)`` — one row per included universe
    asset per trading day. No row is written for an asset the universe
    filter excludes that day (SoT A6.1 stage 1 gates stage 2's input).
    """

    __tablename__ = "asset_factors"

    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    factor_date: Mapped[date] = mapped_column(Date, primary_key=True)

    momentum_3m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    momentum_6m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    dist_52w_high: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    ma20_deviation: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    roe: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    op_margin: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    revenue_growth_yoy: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    debt_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    per: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    pbr: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))

    avg_trading_value_20d: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    volume_cv: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    volatility_60d: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    mdd_60d: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    gap_frequency_60d: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    is_managed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_alert: Mapped[bool] = mapped_column(Boolean, server_default="false")

    financial_data_as_of: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
