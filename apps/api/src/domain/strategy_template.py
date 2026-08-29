"""Strategy template catalog (SoT A7.1 — domain).

Four hardcoded ``StrategyConfig`` presets an owner can start a new strategy
from (SoT A5.3 "템플릿 또는 빈 전략에서 시작한다"). Python constants rather
than a YAML file like ``glossary.ko.yaml`` (SoT A6.12) — unlike glossary
prose, this is not free-text content an owner edits directly; it is four
rows of structured numeric config, and import-time Pydantic validation
(a typo caught immediately, not at first template load in production) is
worth more here than YAML's editing convenience.

Only the numeric/enum values SoT A7.1 states explicitly are populated;
every other ``StrategyConfig`` field is left at its default (SoT A7.1's own
header: "검증된 값 아님, 오너가 편집" — these are starting points, not
complete specs). ``asset_types``/``markets`` are the one inference beyond
literal A7.1 text: templates ①②④ score via ``ai_filter`` (SoT ADR 0011 —
AI scoring is STOCK-only, ETF has no financial statements), and template ③
is explicitly "ETF만" with no AI filter (SoT A6.1 "ETF 전략은 AI 필터 없이
기술적 조건만") — both already reflected in the values below.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.domain.asset import AssetType, Market
from src.domain.strategy_config import (
    AiFilterConfig,
    BuyRules,
    PositionSizing,
    RebalanceConfig,
    RebalanceFrequency,
    SellRules,
    StrategyConfig,
    UniverseConfig,
)


class StrategyTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    description: str
    config: StrategyConfig


_TREND_FOLLOWING = StrategyTemplate(
    key="trend_following",
    name="추세추종",
    description=(
        "권장 입문 템플릿 — 이동평균 정렬과 신고가 근접으로 상승 추세 종목을 매수하고, "
        "손절·트레일링 스탑·이동평균 이탈로 청산합니다."
    ),
    config=StrategyConfig(
        universe=UniverseConfig(
            markets=[Market.KR],
            asset_types=[AssetType.STOCK],
            market_cap_min=Decimal("500000000000"),
            avg_trading_value_min=Decimal("3000000000"),
        ),
        ai_filter=AiFilterConfig(min_score=Decimal("70"), top_n=15),
        buy_rules=BuyRules(
            ma_alignment=[20, 60],
            price_above_ma=20,
            near_high_pct=Decimal("5"),
            near_high_lookback=60,
            momentum_3m_min=Decimal("0"),
        ),
        sell_rules=SellRules(
            stop_loss_pct=Decimal("8"),
            trailing_stop_pct=Decimal("12"),
            price_below_ma=50,
        ),
        position_sizing=PositionSizing(
            max_weight_per_asset=Decimal("0.07"),
            max_positions=12,
            min_cash_weight=Decimal("0.10"),
        ),
        rebalance=RebalanceConfig(frequency=RebalanceFrequency.WEEKLY),
    ),
)

_AI_MOMENTUM = StrategyTemplate(
    key="ai_momentum",
    name="AI 모멘텀",
    description="AI 점수와 모멘텀을 함께 활용해 종목을 선별하고, 점수 약화 시 청산합니다.",
    config=StrategyConfig(
        universe=UniverseConfig(markets=[Market.KR], asset_types=[AssetType.STOCK]),
        ai_filter=AiFilterConfig(min_score=Decimal("75"), top_n=10),
        buy_rules=BuyRules(momentum_3m_min=Decimal("0"), price_above_ma=20),
        sell_rules=SellRules(
            stop_loss_pct=Decimal("8"),
            trailing_stop_pct=Decimal("15"),
            price_below_ma=20,
            ai_score_below=Decimal("55"),
        ),
        position_sizing=PositionSizing(
            max_weight_per_asset=Decimal("0.10"),
            max_positions=10,
            min_cash_weight=Decimal("0.10"),
        ),
        rebalance=RebalanceConfig(frequency=RebalanceFrequency.MONTHLY),
    ),
)

_LOW_VOLATILITY_ETF = StrategyTemplate(
    key="low_volatility_etf",
    name="저변동성 ETF",
    description=(
        "변동성이 낮은 ETF만을 대상으로, AI 필터 없이 기술적 조건만으로 보수적으로 운용합니다."
    ),
    config=StrategyConfig(
        universe=UniverseConfig(markets=[Market.KR], asset_types=[AssetType.ETF]),
        buy_rules=BuyRules(volatility_max_percentile=Decimal("50"), price_above_ma=60),
        sell_rules=SellRules(stop_loss_pct=Decimal("5"), trailing_stop_pct=Decimal("8")),
        position_sizing=PositionSizing(
            max_weight_per_asset=Decimal("0.25"),
            max_positions=6,
            min_cash_weight=Decimal("0.10"),
        ),
        rebalance=RebalanceConfig(frequency=RebalanceFrequency.MONTHLY),
    ),
)

_LARGE_CAP_QUALITY = StrategyTemplate(
    key="large_cap_quality",
    name="대형주 퀄리티",
    description=(
        "AI 점수가 높은 대형주를 장기 보유하며, 낮은 매매 빈도로 안정적인 성과를 추구합니다."
    ),
    config=StrategyConfig(
        universe=UniverseConfig(markets=[Market.KR], asset_types=[AssetType.STOCK]),
        ai_filter=AiFilterConfig(min_score=Decimal("70")),
        buy_rules=BuyRules(price_above_ma=60),
        sell_rules=SellRules(stop_loss_pct=Decimal("10"), ai_score_below=Decimal("50")),
        position_sizing=PositionSizing(
            max_weight_per_asset=Decimal("0.10"),
            max_positions=10,
            min_cash_weight=Decimal("0.05"),
        ),
        rebalance=RebalanceConfig(frequency=RebalanceFrequency.QUARTERLY),
    ),
)

STRATEGY_TEMPLATES: list[StrategyTemplate] = [
    _TREND_FOLLOWING,
    _AI_MOMENTUM,
    _LOW_VOLATILITY_ETF,
    _LARGE_CAP_QUALITY,
]
