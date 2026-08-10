"""Daily OHLCV schema + price data source port (SoT C1/C3 — domain).

``PriceDataSource`` is a separate ``Protocol`` from ``DataSource``
(``src/domain/asset.py``) rather than an extension of it: ticker master and
daily OHLCV are different tables backed by different collection jobs
(``collect_prices`` 16:30, SoT D6). Folding a price method onto
``DataSource.list_tickers()`` would break single responsibility and force
``FakeDataSource`` to carry two unrelated concerns. The ``DATA_SOURCE=fake|krx``
swap (SoT B3) composes both ports independently at the DI root
(``api/deps.py``, out of scope here).

``MarketPrice`` is the SQLAlchemy model that persists
``PriceDataSource.get_daily_ohlcv()`` output (SoT C3). ``MarketPriceRepository``
is the port that wiring goes through — ``src.services.price_sync.sync_prices``
maps ``DailyPriceInfo.ticker`` to ``asset_id`` and upserts via this port, the
same pattern as ``AssetRepository``/``sync_assets`` (issue #27/#29).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class DailyPriceInfo(BaseModel):
    """External-facing representation of a single ticker's daily OHLCV bar.

    Keyed by ``ticker`` rather than ``asset_id`` — like ``TickerInfo``, this
    is what an external source (pykrx) returns; ``src.services.price_sync``
    maps ``ticker`` to ``asset_id`` via ``AssetRepository`` before upserting
    into ``MarketPriceRepository``.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int
    trading_value: Decimal
    market_cap: Decimal | None = None
    halted: bool = False


class PriceDataSource(Protocol):
    """Port for daily OHLCV collection, selected via the ``DATA_SOURCE`` env var.

    ``PykrxPriceDataSource`` (with a FinanceDataReader fallback per SoT C1,
    ``src/adapters/data_sources.py``) is the real implementation behind this
    same interface — SoT B3's fake-by-default pattern, matching
    ``DataSource``/``FakeDataSource``.

    pykrx exposes a date-scoped, all-tickers batch query rather than a
    per-ticker one, so this signature takes a single ``trade_date`` and
    returns every ticker's bar for that day.
    """

    async def get_daily_ohlcv(self, trade_date: date) -> list[DailyPriceInfo]: ...


class MarketPriceRepository(Protocol):
    """Port ``src.services.price_sync`` depends on — same role as ``AssetRepository``.

    Identity is ``(asset_id, date)`` — same shape as ``MarketPrice``'s
    composite primary key. ``upsert`` is ``price_sync``'s only operation;
    ``get_market_caps``/``get_avg_trading_value`` are the bulk read side
    ``src.workers.universe_filter`` (SoT A6.1) depends on instead.
    """

    async def upsert(self, *, asset_id: UUID, bar: DailyPriceInfo) -> MarketPrice:
        """Update the ``(asset_id, bar.date)`` row if one exists, else insert a new one."""
        ...

    async def get_market_caps(self, *, trade_date: date) -> dict[UUID, Decimal | None]:
        """Return every asset's ``market_cap`` on ``trade_date`` (SoT A6.1 universe filter).

        Point-in-time: only rows dated exactly ``trade_date`` are read, so a
        caller can never see a later day's cap by passing an earlier date. An
        ``asset_id`` absent from the returned dict has no ``market_prices``
        row for ``trade_date`` at all (non-trading day, or a collection gap
        for that asset); a present key mapped to ``None`` has a row but a
        ``NULL`` ``market_cap`` column. Callers must treat both the same way
        (``dict.get(asset_id)`` returning ``None``) — fail-closed, not an
        automatic pass (SoT A2 원칙 8).
        """
        ...

    async def get_avg_trading_value(self, *, as_of_date: date, window: int) -> dict[UUID, Decimal]:
        """Per-asset average ``trading_value`` over the trailing ``window`` trading days
        up to and including ``as_of_date`` (SoT A6.1's 20-day average).

        Point-in-time bound: only ``market_prices`` rows dated ``<= as_of_date``
        ever enter the average — a later trading day can never leak into a
        historical run's window (look-ahead prevention, same bounding as
        ``IndexPriceRepository.get_recent``'s ``date <= end_date``). The
        window is the ``window`` most recent *actual* trading days present in
        the data (not a calendar span), matching
        ``market_regime_detection``'s history fetches. An ``asset_id`` with
        no ``market_prices`` rows in that window is absent from the returned
        dict — callers must treat a missing key as "no data", not zero.
        """
        ...


class MarketPrice(Base):
    """Daily OHLCV row (SoT C3 — market_prices).

    Identity is ``(asset_id, date)`` — one row per asset per trading day.
    """

    __tablename__ = "market_prices"

    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    adjusted_close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    volume: Mapped[int] = mapped_column(BigInteger)
    trading_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    halted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
