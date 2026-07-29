"""Ticker master schema + data source port (SoT C1/C3 — domain).

``DataSource`` is the port ``src.services``/``src.workers`` depend on for
ticker-master collection (``src/workers/settings.py`` selects the concrete
implementation via ``DATA_SOURCE``). It lives here —
rather than alongside its concrete implementation in
``src/adapters/data_sources.py`` — for the same reason as
``UserRepository`` (see ``src/domain/user.py``): callers elsewhere in the
codebase need the type for typed parameters, but the import-linter contract
forbids most layers from importing ``src.adapters`` directly. Every layer is
already allowed to import ``domain``, so the port lives here and
implementations satisfy it structurally (Python ``Protocol``, no explicit
inheritance).

``Asset`` is the SQLAlchemy model that persists ``DataSource.list_tickers()``
output (SoT C3) — the upsert wiring between the two is a later issue's
scope; this one only adds the table.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Date, DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base
from src.domain.ids import generate_uuid7


class Exchange(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class Market(StrEnum):
    KR = "KR"


class AssetType(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"


class TickerInfo(BaseModel):
    """External-facing representation of a single listed ticker."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    name: str
    exchange: Exchange
    # No default — a caller that forgets to classify a ticker must fail
    # loudly rather than have it silently upserted as STOCK (SoT 원칙 8).
    asset_type: AssetType


class DataSource(Protocol):
    """Port for ticker-master collection, selected via the ``DATA_SOURCE`` env var.

    ``PykrxDataSource`` (with a KRX 정보데이터시스템 fallback,
    ``src/adapters/data_sources.py``) is the real implementation behind this
    same interface — SoT B3's fake-by-default pattern, matching
    ``LLMClient``/``FakeLLMClient``.
    """

    async def list_tickers(self) -> list[TickerInfo]: ...


class AssetRepository(Protocol):
    """Port ``src.services.asset_sync`` depends on; ``SqlAlchemyAssetRepository`` implements it.

    Scoped to *active* rows only (SoT C3 — asset identity is ticker +
    listing span, not ticker alone): a delisted-then-relisted ticker must
    get a new row rather than reactivating the old one, so this port never
    exposes a lookup or write that could touch an inactive row.
    """

    async def get_active_by_ticker(self, ticker: str, market: Market) -> Asset | None: ...

    async def upsert_active(
        self,
        *,
        ticker: str,
        name: str,
        market: Market,
        asset_type: AssetType,
        exchange: Exchange,
    ) -> Asset:
        """Update the active row for ``(ticker, market)`` if one exists, else insert a new one."""
        ...


class Asset(Base):
    """Ticker master row (SoT C3 — assets).

    Asset identity is ticker + listing span, not ticker alone: a KRX ticker
    code can be reused after delisting, so uniqueness is enforced only among
    active rows (partial index on ``(ticker, market) WHERE is_active``,
    added in the Alembic migration). A relisting under the same ticker gets
    a new row rather than reactivating the old one.
    """

    __tablename__ = "assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=generate_uuid7)
    ticker: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(255))
    market: Mapped[Market] = mapped_column(
        SAEnum(Market, name="market", values_callable=lambda e: [x.value for x in e])
    )
    asset_type: Mapped[AssetType] = mapped_column(
        SAEnum(AssetType, name="asset_type", values_callable=lambda e: [x.value for x in e])
    )
    exchange: Mapped[Exchange] = mapped_column(
        SAEnum(Exchange, name="exchange", values_callable=lambda e: [x.value for x in e])
    )
    sector: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3), server_default="KRW")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    listed_at: Mapped[date | None] = mapped_column(Date)
    delisted_at: Mapped[date | None] = mapped_column(Date)
    is_managed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_alert: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
