"""``STRATEGY_TEMPLATES`` seed-value tests (SoT A7.1 — domain).

Asserts the four templates match A7.1's stated values exactly and that each
``config`` parses as a valid ``StrategyConfig`` (import-time construction
already proves parseability — see ``strategy_template.py``'s module
docstring — this module locks the *values* against silent drift).
"""

from __future__ import annotations

from decimal import Decimal

from src.domain.asset import AssetType, Market
from src.domain.strategy_config import RebalanceFrequency, StrategyConfig
from src.domain.strategy_template import STRATEGY_TEMPLATES, StrategyTemplate


def test_exactly_four_templates_seeded() -> None:
    assert len(STRATEGY_TEMPLATES) == 4
    assert [t.key for t in STRATEGY_TEMPLATES] == [
        "trend_following",
        "ai_momentum",
        "low_volatility_etf",
        "large_cap_quality",
    ]


def test_every_template_config_parses_as_strategy_config() -> None:
    for template in STRATEGY_TEMPLATES:
        reparsed = StrategyConfig.model_validate(template.config.model_dump())
        assert isinstance(reparsed, StrategyConfig)


def _by_key(key: str) -> StrategyTemplate:
    return next(t for t in STRATEGY_TEMPLATES if t.key == key)


def test_trend_following_matches_a7_1_seed_values() -> None:
    config = _by_key("trend_following").config

    assert config.universe.asset_types == [AssetType.STOCK]
    assert config.universe.markets == [Market.KR]
    assert config.universe.market_cap_min == Decimal("500000000000")
    assert config.universe.avg_trading_value_min == Decimal("3000000000")
    assert config.ai_filter.min_score == Decimal("70")
    assert config.ai_filter.top_n == 15
    assert config.buy_rules.ma_alignment == [20, 60]
    assert config.buy_rules.price_above_ma == 20
    assert config.buy_rules.near_high_pct == Decimal("5")
    assert config.buy_rules.near_high_lookback == 60
    assert config.buy_rules.momentum_3m_min == Decimal("0")
    assert config.sell_rules.stop_loss_pct == Decimal("8")
    assert config.sell_rules.trailing_stop_pct == Decimal("12")
    assert config.sell_rules.price_below_ma == 50
    assert config.position_sizing.max_weight_per_asset == Decimal("0.07")
    assert config.position_sizing.max_positions == 12
    assert config.position_sizing.min_cash_weight == Decimal("0.10")
    assert config.rebalance.frequency == RebalanceFrequency.WEEKLY


def test_ai_momentum_matches_a7_1_seed_values() -> None:
    config = _by_key("ai_momentum").config

    assert config.ai_filter.min_score == Decimal("75")
    assert config.ai_filter.top_n == 10
    assert config.buy_rules.momentum_3m_min == Decimal("0")
    assert config.buy_rules.price_above_ma == 20
    assert config.sell_rules.stop_loss_pct == Decimal("8")
    assert config.sell_rules.trailing_stop_pct == Decimal("15")
    assert config.sell_rules.price_below_ma == 20
    assert config.sell_rules.ai_score_below == Decimal("55")
    assert config.position_sizing.max_weight_per_asset == Decimal("0.10")
    assert config.position_sizing.max_positions == 10
    assert config.position_sizing.min_cash_weight == Decimal("0.10")
    assert config.rebalance.frequency == RebalanceFrequency.MONTHLY


def test_low_volatility_etf_matches_a7_1_seed_values() -> None:
    config = _by_key("low_volatility_etf").config

    assert config.universe.asset_types == [AssetType.ETF]
    assert config.ai_filter.min_score is None
    assert config.ai_filter.top_n is None
    assert config.buy_rules.volatility_max_percentile == Decimal("50")
    assert config.buy_rules.price_above_ma == 60
    assert config.sell_rules.stop_loss_pct == Decimal("5")
    assert config.sell_rules.trailing_stop_pct == Decimal("8")
    assert config.position_sizing.max_weight_per_asset == Decimal("0.25")
    assert config.position_sizing.max_positions == 6
    assert config.position_sizing.min_cash_weight == Decimal("0.10")
    assert config.rebalance.frequency == RebalanceFrequency.MONTHLY


def test_large_cap_quality_matches_a7_1_seed_values() -> None:
    config = _by_key("large_cap_quality").config

    assert config.ai_filter.min_score == Decimal("70")
    assert config.buy_rules.price_above_ma == 60
    assert config.sell_rules.stop_loss_pct == Decimal("10")
    assert config.sell_rules.ai_score_below == Decimal("50")
    assert config.position_sizing.max_weight_per_asset == Decimal("0.10")
    assert config.position_sizing.max_positions == 10
    assert config.position_sizing.min_cash_weight == Decimal("0.05")
    assert config.rebalance.frequency == RebalanceFrequency.QUARTERLY
