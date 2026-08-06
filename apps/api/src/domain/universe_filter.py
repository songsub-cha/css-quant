"""Universe filter DTOs (SoT A6.1 — domain).

A6.1's first step judges, for a given trading day, which active KR STOCK
assets belong in the AI-score pipeline's universe: market cap and 20-day
average trading value floors, a minimum listed-days age, and exclusion of
managed/investment-alert issues and preferred stock. No new table is added
here — the judgement reads only ``assets`` and ``market_prices`` (see
``src.workers.universe_filter``) and produces no persisted row of its own;
these DTOs are the pure function's input/output shape
(``src.engine.universe_filter.filter_universe``).

``UniverseCandidate.market_cap``/``avg_trading_value_20d`` are ``None`` when
that day's data is simply missing for the asset (collection gap or a
non-trading date) — distinct from a populated value that happens to fall
below a threshold. The engine treats a missing value as its own exclusion
reason (fail-closed per SoT A2 원칙 8: "판정 불가"는 "조건 미해당"이 아니다),
not as an automatic pass.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UniverseExclusionReason(StrEnum):
    MARKET_CAP_BELOW_MIN = "MARKET_CAP_BELOW_MIN"
    MARKET_CAP_DATA_MISSING = "MARKET_CAP_DATA_MISSING"
    AVG_TRADING_VALUE_BELOW_MIN = "AVG_TRADING_VALUE_BELOW_MIN"
    AVG_TRADING_VALUE_DATA_MISSING = "AVG_TRADING_VALUE_DATA_MISSING"
    LISTED_LESS_THAN_MIN_DAYS = "LISTED_LESS_THAN_MIN_DAYS"
    MANAGED_ISSUE = "MANAGED_ISSUE"
    INVESTMENT_ALERT = "INVESTMENT_ALERT"
    PREFERRED_STOCK = "PREFERRED_STOCK"


class UniverseThresholds(BaseModel):
    """Configurable cutoffs (SoT A6.1) — sourced from ``config.Settings``, never hardcoded."""

    model_config = ConfigDict(frozen=True)

    market_cap_min: Decimal
    avg_trading_value_min: Decimal
    min_listed_days: int


class UniverseCandidate(BaseModel):
    """One active KR STOCK asset's already-fetched inputs for one trading day's judgement.

    ``src.workers.universe_filter.evaluate_universe`` builds these from
    ``AssetRepository.list_active(Market.KR, AssetType.STOCK)`` joined with
    ``MarketPriceRepository``'s bulk queries — market/asset_type/is_active
    are the candidate-selection filter itself (ETF and inactive rows never
    become a ``UniverseCandidate``), so they are not carried as fields here.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    name: str
    is_managed: bool
    is_alert: bool
    listed_at: date | None
    market_cap: Decimal | None
    avg_trading_value_20d: Decimal | None


class UniverseFilterResult(BaseModel):
    """One candidate's verdict — ``included`` iff ``exclusion_reasons`` is empty.

    Multiple reasons can co-occur (e.g. below both market cap and trading
    value floors) — ``filter_universe`` checks every condition independently
    rather than short-circuiting on the first violation.
    """

    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    included: bool
    exclusion_reasons: list[UniverseExclusionReason]
