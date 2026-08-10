"""Unit tests for ``src.engine.universe_filter`` (SoT A6.1).

Pure DB-free judgement — no fakes, no fixtures, just DTOs and asserted
exclusion reasons, same style as ``test_market_regime_engine.py``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from src.domain.universe_filter import (
    UniverseCandidate,
    UniverseExclusionReason,
    UniverseThresholds,
)
from src.engine.universe_filter import filter_universe

_AS_OF = date(2026, 8, 7)
_THRESHOLDS = UniverseThresholds(
    market_cap_min=Decimal("300000000000"),
    avg_trading_value_min=Decimal("1000000000"),
    min_listed_days=60,
)


def _candidate(
    *,
    name: str = "삼성전자",
    is_managed: bool = False,
    is_alert: bool = False,
    listed_at: date | None = date(2000, 1, 1),
    market_cap: Decimal | None = Decimal("400000000000"),
    avg_trading_value_20d: Decimal | None = Decimal("2000000000"),
) -> UniverseCandidate:
    return UniverseCandidate(
        asset_id=uuid4(),
        name=name,
        is_managed=is_managed,
        is_alert=is_alert,
        listed_at=listed_at,
        market_cap=market_cap,
        avg_trading_value_20d=avg_trading_value_20d,
    )


def test_a_fully_qualifying_candidate_is_included() -> None:
    (result,) = filter_universe([_candidate()], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is True
    assert result.exclusion_reasons == []


def test_market_cap_below_min_is_excluded() -> None:
    candidate = _candidate(market_cap=Decimal("299999999999"))

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert result.exclusion_reasons == [UniverseExclusionReason.MARKET_CAP_BELOW_MIN]


def test_market_cap_exactly_at_min_is_included() -> None:
    candidate = _candidate(market_cap=Decimal("300000000000"))

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is True


def test_market_cap_missing_is_excluded_as_data_missing_not_below_min() -> None:
    candidate = _candidate(market_cap=None)

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert result.exclusion_reasons == [UniverseExclusionReason.MARKET_CAP_DATA_MISSING]


def test_avg_trading_value_below_min_is_excluded() -> None:
    candidate = _candidate(avg_trading_value_20d=Decimal("999999999"))

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert result.exclusion_reasons == [UniverseExclusionReason.AVG_TRADING_VALUE_BELOW_MIN]


def test_avg_trading_value_exactly_at_min_is_included() -> None:
    candidate = _candidate(avg_trading_value_20d=Decimal("1000000000"))

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is True


def test_avg_trading_value_missing_is_excluded_as_data_missing() -> None:
    candidate = _candidate(avg_trading_value_20d=None)

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert result.exclusion_reasons == [UniverseExclusionReason.AVG_TRADING_VALUE_DATA_MISSING]


def test_listed_less_than_min_days_is_excluded() -> None:
    candidate = _candidate(listed_at=_AS_OF - timedelta(days=59))

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert result.exclusion_reasons == [UniverseExclusionReason.LISTED_LESS_THAN_MIN_DAYS]


def test_listed_exactly_min_days_is_included() -> None:
    candidate = _candidate(listed_at=_AS_OF - timedelta(days=60))

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is True


def test_listed_at_null_is_included_not_excluded() -> None:
    """SoT A6.1 policy decision: listed_at is always NULL today (no collection
    path fills it yet), so treating NULL as fail-closed-exclude would empty
    the whole universe. NULL is "unknown", not "too recently listed"."""
    candidate = _candidate(listed_at=None)

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is True


def test_managed_issue_is_excluded() -> None:
    candidate = _candidate(is_managed=True)

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert result.exclusion_reasons == [UniverseExclusionReason.MANAGED_ISSUE]


def test_investment_alert_is_excluded() -> None:
    candidate = _candidate(is_alert=True)

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert result.exclusion_reasons == [UniverseExclusionReason.INVESTMENT_ALERT]


def test_preferred_stock_suffix_is_excluded() -> None:
    for name in ["삼성전자우", "현대차2우B", "코오롱글로벌우B"]:
        candidate = _candidate(name=name)

        (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

        assert result.included is False, name
        assert result.exclusion_reasons == [UniverseExclusionReason.PREFERRED_STOCK]


def test_ordinary_common_stock_name_is_not_flagged_as_preferred() -> None:
    candidate = _candidate(name="삼성전자")

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert UniverseExclusionReason.PREFERRED_STOCK not in result.exclusion_reasons


def test_multiple_violations_are_all_reported() -> None:
    candidate = _candidate(
        market_cap=Decimal("1"),
        avg_trading_value_20d=Decimal("1"),
        is_managed=True,
    )

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.included is False
    assert set(result.exclusion_reasons) == {
        UniverseExclusionReason.MARKET_CAP_BELOW_MIN,
        UniverseExclusionReason.AVG_TRADING_VALUE_BELOW_MIN,
        UniverseExclusionReason.MANAGED_ISSUE,
    }


def test_asset_id_is_preserved_in_result() -> None:
    candidate = _candidate()

    (result,) = filter_universe([candidate], as_of_date=_AS_OF, thresholds=_THRESHOLDS)

    assert result.asset_id == candidate.asset_id
