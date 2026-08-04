"""``get_krx_trading_days`` (SoT B4.2/C2 — adapters layer).

No DB/network dependency: ``exchange_calendars`` ships its own holiday
calendar data, so this runs fully offline like every other test in this
suite.
"""

from __future__ import annotations

from datetime import date

from src.adapters.trading_calendar import get_krx_trading_days


def test_get_krx_trading_days_excludes_weekend() -> None:
    # 2024-09-13 (Fri) .. 2024-09-15 (Sun) — Saturday/Sunday must be excluded.
    days = get_krx_trading_days(date(2024, 9, 13), date(2024, 9, 15))

    assert days == [date(2024, 9, 13)]


def test_get_krx_trading_days_excludes_chuseok_holiday() -> None:
    # 2024 Chuseok holiday ran 2024-09-16 .. 2024-09-18 (Mon-Wed) — a
    # multi-day KRX holiday embedded in an otherwise-ordinary work week.
    days = get_krx_trading_days(date(2024, 9, 13), date(2024, 9, 20))

    assert days == [date(2024, 9, 13), date(2024, 9, 19), date(2024, 9, 20)]


def test_get_krx_trading_days_single_day_range_is_inclusive() -> None:
    trade_date = date(2026, 7, 29)

    days = get_krx_trading_days(trade_date, trade_date)

    assert days == [trade_date]
