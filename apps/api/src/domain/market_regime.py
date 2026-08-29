"""Market regime + market-shock circuit-breaker schema (SoT A6.2/A6.3/C3 — domain).

``market_regimes`` is the first consumer of ``index_prices`` (SoT A6.2/A6.3):
one row per trading day recording whether the market is ``NORMAL`` or
``DEFENSIVE`` (200-day KOSPI MA + VKOSPI/20-day-volatility judgement, with
hysteresis) and whether a same-day market shock fired (KOSPI -3%+ single-day
drop OR VKOSPI over 1.5x its trailing 20-day average). The judgement and
shock-detection math itself is pure and lives in ``src.engine.market_regime``
(SoT A2 principle 7 — numbers are deterministic code); this module only adds
the table, the port, and the DTO the engine's output gets upserted through
(same fetch-then-upsert split as ``IndexPriceRepository``).

Identity is ``regime_date`` alone (no composite key) — unlike
``index_prices``, there is exactly one market-wide regime per trading day,
not one per index.

Wiring an actual caller (Arq cron registration, ``job_runs`` bookkeeping,
the risk engine's new-buy circuit-breaker hookup) is issue #39/Phase 7's
scope — this module, plus ``src.engine.market_regime`` and
``src.workers.market_regime_detection``, only add the callable pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Date, DateTime, Numeric, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class RegimeStatus(StrEnum):
    NORMAL = "NORMAL"
    DEFENSIVE = "DEFENSIVE"


class InsufficientPriceHistoryError(Exception):
    """Raised when the KOSPI close history handed to the engine is shorter than a
    required window (200 trading days for the moving average, 21 for the daily
    returns feeding the 20-day volatility).

    Fail-closed (SoT A2 principle 8 / A6.4): the caller must not proceed with a
    partial-window judgement, not silently degrade to whatever data exists.
    """


class MarketRegimeInfo(BaseModel):
    """External-facing representation of one trading day's regime + shock verdict.

    ``src.workers.market_regime_detection.detect_market_regime`` builds one of
    these from ``src.engine.market_regime``'s pure output and passes it to
    ``MarketRegimeRepository.upsert`` — same fetch-then-upsert split as
    ``IndexPriceInfo``/``IndexPriceRepository.upsert``.
    """

    model_config = ConfigDict(frozen=True)

    regime_date: date
    regime: RegimeStatus
    kospi_close: Decimal
    kospi_ma200: Decimal
    vkospi: Decimal | None
    kospi_volatility_20d: Decimal
    market_shock: bool
    signals: dict[str, Any]


class MarketRegimeRepository(Protocol):
    """Port ``src.workers.market_regime_detection`` depends on.

    Identity is ``regime_date``, matching ``MarketRegime``'s primary key.
    ``get_recent`` backs the hysteresis lookup: DEFENSIVE -> NORMAL requires 3
    consecutive trading days of a satisfied raw condition, so the engine needs
    the last couple of days' regime + raw verdict before judging today's.
    """

    async def upsert(self, *, regime: MarketRegimeInfo) -> MarketRegime:
        """Update the ``regime.regime_date`` row if one exists, else insert a new one."""
        ...

    async def get_recent(self, *, before_date: date, limit: int) -> list[MarketRegime]:
        """Return up to ``limit`` rows with ``regime_date < before_date``, ordered
        ``regime_date`` descending (most recent first).

        Strictly-before (not ``<=``) so that re-running today's detection never
        sees today's own (possibly already-upserted) row as "yesterday" —
        required for idempotent re-runs to reproduce the same hysteresis input.
        """
        ...

    async def get_by_date(self, *, regime_date: date) -> MarketRegime | None:
        """Return the row for exactly ``regime_date``, or ``None`` if not yet recorded.

        Unlike ``get_recent``'s strict ``<``, this looks up *today's own* row —
        ``src.workers.score_calculation`` needs the regime already in effect
        for the day it's scoring, not yesterday's. It also backs the A6.4
        quality gate's indicator check: a row's mere existence for today is
        the evidence that ``detect_market_regime`` could compute the 200-day
        KOSPI MA (it raises ``InsufficientPriceHistoryError`` and never
        upserts otherwise).
        """
        ...


class MarketRegime(Base):
    """Daily market regime + shock row (SoT A6.2/A6.3/C3 — ``market_regimes``).

    ``vkospi`` is nullable — VKOSPI collection can lag/gap independently of
    KOSPI (SoT A6.2's VKOSPI-missing fallback to 20-day KOSPI-return
    volatility). ``kospi_volatility_20d`` is always populated: it only depends
    on KOSPI closes, so it is computed regardless of whether VKOSPI is
    available that day. ``signals`` carries the raw, pre-hysteresis
    diagnostic values (today's raw NORMAL-condition verdict, the shock legs'
    raw inputs) that ``get_recent`` callers need — see
    ``src.engine.market_regime.judge_regime``'s docstring for why hysteresis
    is applied against the *raw* verdict, not the ``regime`` column.
    """

    __tablename__ = "market_regimes"

    regime_date: Mapped[date] = mapped_column(Date, primary_key=True)
    regime: Mapped[RegimeStatus] = mapped_column(
        SAEnum(RegimeStatus, name="regime_status", values_callable=lambda e: [x.value for x in e])
    )
    kospi_close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    kospi_ma200: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    vkospi: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    kospi_volatility_20d: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    market_shock: Mapped[bool] = mapped_column(Boolean)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
