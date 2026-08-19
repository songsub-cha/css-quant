"""Strategy ``config`` schema (SoT A5.3/A6.5 — domain).

``StrategyConfig`` is the nested Pydantic shape persisted in
``strategies.config`` (jsonb, see ``src.domain.strategy.Strategy``). It is
the sole validation boundary for a strategy's trading rules — the API layer
(``src/api/v1/strategies.py``) accepts/returns it directly as a request/
response field, so an invalid config is rejected with 422 before it ever
reaches the service or a repository (SoT A5.3 "잘못된 설정은 저장 전
검증된다"). ``execution_mode`` is deliberately **not** a field here even
though SoT A6.5 lists it alongside this config — see ``strategy.py``'s
module docstring for why it is a ``strategies`` table column instead.

Every sub-model field is optional (SoT A5.3 "빈 전략에서 시작한다" — a
strategy can be created with a bare/partial config and filled in later); the
validators below only constrain *values that are present*, they never
require a field to exist. This is a deliberate reading of A6.5's config
list, which does not mark ``position_sizing``/``rebalance.frequency`` as
optional in the prose the way ``ai_filter``/``buy_rules`` fields are (``?``
suffixed) — enforcing that literally would make an empty starting strategy
impossible to represent, contradicting A5.3.

**Percentage convention** (undocumented in SoT prose, fixed here for
internal consistency): fields SoT explicitly scopes to "0~100" (``min_score``,
``ai_score_below``, ``volatility_max_percentile``) are percentage *points* on
that 0-100 scale. ``position_sizing`` fields are fractions on a 0-1 scale,
matching A6.5's explicit ``max_participation_pct`` default of literal
``0.05`` (not ``5``). ``sell_rules``/``buy_rules`` percentage-drop fields
(``stop_loss_pct``, ``trailing_stop_pct``, ``take_profit_pct``,
``near_high_pct``) are magnitudes on a percentage-point scale (e.g. ``8``
for SoT's "-8%"), matching how A7.1's template prose writes them.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.asset import AssetType, Market


class RebalanceFrequency(StrEnum):
    """SoT A6.5 ``rebalance.frequency`` — uppercase values, see ``RebalanceConfig``."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class UniverseConfig(BaseModel):
    """SoT A6.5 ``universe``: markets, asset_types, sectors?, market_cap_min?,
    avg_trading_value_min?.
    """

    model_config = ConfigDict(frozen=True)

    markets: list[Market] = Field(default_factory=list)
    asset_types: list[AssetType] = Field(default_factory=list)
    sectors: list[str] | None = None
    market_cap_min: Decimal | None = Field(default=None, gt=0)
    avg_trading_value_min: Decimal | None = Field(default=None, gt=0)


class AiFilterConfig(BaseModel):
    """SoT A6.5 ``ai_filter``: min_score? (0~100), top_n?."""

    model_config = ConfigDict(frozen=True)

    min_score: Decimal | None = Field(default=None, ge=0, le=100)
    top_n: int | None = Field(default=None, gt=0)


class BuyRules(BaseModel):
    """SoT A6.5 ``buy_rules``.

    ``ma_alignment`` must be exactly two strictly-ascending positive
    integers (e.g. ``[20, 60]`` meaning "20일 이동평균 > 60일 이동평균").
    ``near_high_pct``/``near_high_lookback`` are co-dependent — SoT phrases
    them as one condition ("60일 신고가 5% 이내"), so one present without the
    other is a malformed rule rather than two independent optional knobs.
    """

    model_config = ConfigDict(frozen=True)

    momentum_3m_min: Decimal | None = None
    momentum_6m_min: Decimal | None = None
    price_above_ma: int | None = Field(default=None, gt=0)
    ma_alignment: list[int] | None = None
    near_high_pct: Decimal | None = Field(default=None, gt=0)
    near_high_lookback: int | None = Field(default=None, gt=0)
    volatility_max_percentile: Decimal | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _validate_ma_alignment(self) -> BuyRules:
        if self.ma_alignment is None:
            return self
        if len(self.ma_alignment) != 2:
            raise ValueError("ma_alignment must contain exactly two moving-average windows")
        short_window, long_window = self.ma_alignment
        if short_window <= 0 or long_window <= 0:
            raise ValueError("ma_alignment windows must be positive")
        if short_window >= long_window:
            raise ValueError("ma_alignment must be strictly ascending (short window < long window)")
        return self

    @model_validator(mode="after")
    def _validate_near_high_co_presence(self) -> BuyRules:
        has_pct = self.near_high_pct is not None
        has_lookback = self.near_high_lookback is not None
        if has_pct != has_lookback:
            raise ValueError("near_high_pct and near_high_lookback must be set together")
        return self


class SellRules(BaseModel):
    """SoT A6.5 ``sell_rules`` — evaluated in this fixed order (SoT prose), all optional.

    1. ``stop_loss_pct`` 2. ``trailing_stop_pct`` 3. ``price_below_ma``
    4. ``ai_score_below``/``momentum_below`` 5. ``take_profit_pct``
    6. ``holding_days_max``
    """

    model_config = ConfigDict(frozen=True)

    stop_loss_pct: Decimal | None = Field(default=None, gt=0)
    trailing_stop_pct: Decimal | None = Field(default=None, gt=0)
    price_below_ma: int | None = Field(default=None, gt=0)
    ai_score_below: Decimal | None = Field(default=None, ge=0, le=100)
    momentum_below: Decimal | None = None
    take_profit_pct: Decimal | None = Field(default=None, gt=0)
    holding_days_max: int | None = Field(default=None, gt=0)


class PositionSizing(BaseModel):
    """SoT A6.5 ``position_sizing`` — fractions on a 0-1 scale (module docstring)."""

    model_config = ConfigDict(frozen=True)

    max_weight_per_asset: Decimal | None = Field(default=None, gt=0, le=1)
    max_positions: int | None = Field(default=None, gt=0)
    min_cash_weight: Decimal | None = Field(default=None, ge=0, le=1)
    max_participation_pct: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)


class RebalanceConfig(BaseModel):
    """SoT A6.5 ``rebalance.frequency``: DAILY | WEEKLY | MONTHLY | QUARTERLY.

    Uppercase literal values (unlike ``StrategyStatus``/``ExecutionMode`` in
    ``strategy.py``) — this enum lives inside ``config`` jsonb, not a
    Postgres enum column, so SoT B5.2's lowercase-persisted-enum trap does
    not apply here. SoT A6.5 writes these values in uppercase and the Zod
    schema on the frontend side is expected to mirror that literally.
    """

    model_config = ConfigDict(frozen=True)

    frequency: RebalanceFrequency | None = None


class StrategyConfig(BaseModel):
    """SoT A6.5 full ``config`` shape — module docstring covers the two
    interpretation decisions (optional-everywhere, percentage convention).
    """

    model_config = ConfigDict(frozen=True)

    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    ai_filter: AiFilterConfig = Field(default_factory=AiFilterConfig)
    buy_rules: BuyRules = Field(default_factory=BuyRules)
    sell_rules: SellRules = Field(default_factory=SellRules)
    position_sizing: PositionSizing = Field(default_factory=PositionSizing)
    rebalance: RebalanceConfig = Field(default_factory=RebalanceConfig)
