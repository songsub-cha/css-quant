"""``StrategyConfig`` unit validation tests (SoT A5.3/A6.5 — domain schema).

Pure Pydantic validation, no DB/repository involved — the same isolation
level as ``test_watchlist_service.py``'s fakes, one level further in since
this module has no repository dependency at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.strategy_config import (
    AiFilterConfig,
    BuyRules,
    PositionSizing,
    StrategyConfig,
)


def test_empty_config_is_valid() -> None:
    """SoT A5.3 "빈 전략에서 시작한다" — every field must be optional."""
    config = StrategyConfig()

    assert config.universe.markets == []
    assert config.ai_filter.min_score is None
    assert config.position_sizing.max_participation_pct == Decimal("0.05")


def test_fully_populated_config_round_trips() -> None:
    payload = {
        "universe": {"markets": ["KR"], "asset_types": ["STOCK"]},
        "ai_filter": {"min_score": "70", "top_n": 15},
        "buy_rules": {
            "ma_alignment": [20, 60],
            "near_high_pct": "5",
            "near_high_lookback": 60,
        },
        "sell_rules": {"stop_loss_pct": "8", "trailing_stop_pct": "12"},
        "position_sizing": {"max_weight_per_asset": "0.07", "max_positions": 12},
        "rebalance": {"frequency": "WEEKLY"},
    }

    config = StrategyConfig.model_validate(payload)

    assert config.ai_filter.min_score == Decimal("70")
    assert config.buy_rules.ma_alignment == [20, 60]
    assert config.rebalance.frequency is not None
    assert config.rebalance.frequency.value == "WEEKLY"


def test_ai_filter_min_score_above_100_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AiFilterConfig(min_score=Decimal("101"))


def test_ai_filter_min_score_below_0_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AiFilterConfig(min_score=Decimal("-1"))


def test_ma_alignment_wrong_length_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BuyRules(ma_alignment=[20])


def test_ma_alignment_reversed_order_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BuyRules(ma_alignment=[60, 20])


def test_ma_alignment_equal_windows_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BuyRules(ma_alignment=[20, 20])


def test_ma_alignment_valid_ascending_pair_is_accepted() -> None:
    rules = BuyRules(ma_alignment=[20, 60])

    assert rules.ma_alignment == [20, 60]


def test_near_high_pct_without_lookback_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BuyRules(near_high_pct=Decimal("5"))


def test_near_high_lookback_without_pct_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BuyRules(near_high_lookback=60)


def test_near_high_pct_and_lookback_together_is_accepted() -> None:
    rules = BuyRules(near_high_pct=Decimal("5"), near_high_lookback=60)

    assert rules.near_high_pct == Decimal("5")
    assert rules.near_high_lookback == 60


def test_position_sizing_max_weight_per_asset_above_1_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PositionSizing(max_weight_per_asset=Decimal("1.5"))


def test_position_sizing_max_weight_per_asset_zero_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PositionSizing(max_weight_per_asset=Decimal("0"))


def test_position_sizing_min_cash_weight_above_1_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PositionSizing(min_cash_weight=Decimal("1.1"))


def test_position_sizing_max_participation_pct_default_is_0_05() -> None:
    sizing = PositionSizing()

    assert sizing.max_participation_pct == Decimal("0.05")
