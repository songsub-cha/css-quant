"""XKRX trading-day calendar utility (SoT B4.2/C2 — adapters).

SoT B4.2 names ``exchange_calendars`` (XKRX) as how trade-day judgement
should be made, and C2's backfill-vs-incremental split needs "every KRX
trading day between a start and end date" to drive a date-range backfill.
Neither existed anywhere in this repository before this module — this is
the first import of ``exchange_calendars`` in the codebase.

Kept in ``adapters`` rather than ``domain``: this is a thin wrapper around a
third-party calendar library, the same rationale ``data_sources.py`` and
``dart_financial_data_source.py`` live in this layer rather than ``domain``
(SoT B2 — "adapters는 domain만 import", domain itself must stay pure).
"""

from __future__ import annotations

from datetime import date

import exchange_calendars as xcals

_XKRX_CALENDAR_NAME = "XKRX"


def get_krx_trading_days(start: date, end: date) -> list[date]:
    """Return every KRX trading day in ``[start, end]``, inclusive, weekends/holidays excluded."""
    calendar = xcals.get_calendar(_XKRX_CALENDAR_NAME)
    sessions = calendar.sessions_in_range(start.isoformat(), end.isoformat())
    return list(sessions.date)
