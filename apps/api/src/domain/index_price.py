"""KOSPI/VKOSPI index daily OHLCV schema + data source port (SoT A6.2/A6.3/C1 — domain).

``market_prices`` (``src/domain/market_price.py``) keys on ``asset_id`` with a
FK to ``assets.id`` — an index is not a tradable, listed instrument, so it has
no ``assets`` row to key off of. Rather than force a nullable/fake FK onto
that table, this module defines an independent ``index_prices`` table keyed
on ``(index_code, date)`` with no ``assets`` reference at all.

``IndexPriceDataSource``/``IndexPriceRepository`` mirror
``PriceDataSource``/``MarketPriceRepository``'s shape (same
fetch-then-upsert split) but are separate Protocols rather than a shared one
— identity here is ``index_code``, not ``asset_id``, so a shared interface
would need to fork on that distinction anyway.

This module adds collection plumbing plus the read path
(``IndexPriceRepository.get_recent``) that the 200-day MA / 20-day
volatility calculations and regime/circuit-breaker judgement
(SoT A6.2 market regime, A6.3 market-shock circuit breaker) consume — see
``src.engine.market_regime`` and ``src.workers.market_regime_detection``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Date, DateTime, Numeric, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class IndexCode(StrEnum):
    KOSPI = "KOSPI"
    VKOSPI = "VKOSPI"


class IndexPriceInfo(BaseModel):
    """External-facing representation of a single index's daily OHLCV bar.

    Unlike ``DailyPriceInfo``, there is no ``adjusted_close``/``market_cap``/
    ``halted`` — an index has no splits/dividends or listed market cap, and
    trading halts are a per-instrument concept that does not apply here.
    """

    model_config = ConfigDict(frozen=True)

    index_code: IndexCode
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trading_value: Decimal


class IndexPriceDataSource(Protocol):
    """Port for KOSPI/VKOSPI daily OHLCV collection, selected via ``DATA_SOURCE``.

    ``PykrxIndexPriceDataSource`` (``src/adapters/data_sources.py``) is the
    real implementation — SoT B3's fake-by-default pattern. Only two indices
    are in scope, so unlike ``PriceDataSource`` this is not a bulk
    all-tickers query; the concrete adapter fetches each index individually.
    """

    async def get_daily_ohlcv(self, trade_date: date) -> list[IndexPriceInfo]: ...


class IndexPriceRepository(Protocol):
    """Port ``src.services.index_price_sync`` depends on — same role as ``MarketPriceRepository``.

    Identity is ``(index_code, date)``, matching ``IndexPrice``'s composite
    primary key. Like ``MarketPriceRepository``, ``upsert`` is the only
    operation this port exposes — the sync service never needs to read a bar
    back before deciding whether to insert or update.
    """

    async def upsert(self, *, bar: IndexPriceInfo) -> IndexPrice:
        """Update the ``(bar.index_code, bar.date)`` row if one exists, else insert a new one."""
        ...

    async def get_recent(
        self, *, index_code: IndexCode, end_date: date, limit: int
    ) -> list[IndexPriceInfo]:
        """Return up to ``limit`` bars with ``date <= end_date``, ordered date ascending.

        Backs the 200-day MA / 20-day volatility calculations
        (``src.engine.market_regime``), which need the trailing window in
        chronological order. Implementations select ``ORDER BY date DESC
        LIMIT limit`` (to get the *most recent* ``limit`` rows) and then
        reverse — a plain ``ORDER BY date ASC LIMIT limit`` would instead
        return the *oldest* ``limit`` rows, which is not what a trailing
        window means.
        """
        ...


class IndexPrice(Base):
    """Daily index OHLCV row (SoT A6.2/A6.3 — index_prices).

    Identity is ``(index_code, date)`` — one row per index per trading day.
    No FK to ``assets`` — an index is not a tradable instrument (see module
    docstring).
    """

    __tablename__ = "index_prices"

    index_code: Mapped[IndexCode] = mapped_column(
        SAEnum(IndexCode, name="index_code", values_callable=lambda e: [x.value for x in e]),
        primary_key=True,
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    volume: Mapped[int] = mapped_column(BigInteger)
    trading_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
