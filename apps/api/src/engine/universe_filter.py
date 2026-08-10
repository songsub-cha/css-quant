"""Pure universe filter judgement (SoT A6.1 — engine).

Deterministic, DB-free judgement only (SoT A2 원칙 7 — "숫자는 결정론적
코드"): every candidate's inputs are already fetched by
``src.workers.universe_filter``, so this function only classifies. All I/O —
listing active KR STOCK assets and fetching market cap / 20-day average
trading value — is the worker's job; this module imports only
``src.domain``, per the layer contract (``src.engine`` may depend on
domain/adapters, never services/api/workers).

Two known data gaps affect accuracy without blocking this filter (see the
issue #56 plan):

- ``is_managed``/``is_alert`` are always ``False`` today (issue #49, blocked
  `css:adr` on a KRX login wall) — checked correctly here regardless, so
  these conditions become live automatically once #49 is resolved, no code
  change needed.
- ``listed_at`` is currently always ``NULL`` (no collection path fills it
  yet) — a ``None`` value is treated as "unknown, don't exclude" rather than
  fail-closed, because fail-closed here would empty the entire universe
  today and make every downstream pipeline stage unverifiable. Once a
  collection path fills ``listed_at``, the minimum-listed-days condition
  starts applying to real dates automatically.

Preferred stock has no dedicated schema column; KRX naming convention
suffixes preferred tickers' names with ``우``/``N우``/``N우B`` (e.g.
"삼성전자우", "현대차2우B"), so ``_is_preferred_stock`` uses a name-suffix
regex heuristic. Known limitation: a common-stock name that happens to end
in this pattern would be misclassified — there is no ground-truth column to
check against.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from src.domain.universe_filter import (
    UniverseCandidate,
    UniverseExclusionReason,
    UniverseFilterResult,
    UniverseThresholds,
)

# KRX preferred-stock naming convention: optional leading digit(s) + "우" +
# optional "B" at the very end of the name (e.g. "삼성전자우", "현대차2우B").
_PREFERRED_STOCK_SUFFIX = re.compile(r"\d*우B?$")


def _is_preferred_stock(name: str) -> bool:
    return bool(_PREFERRED_STOCK_SUFFIX.search(name))


def filter_universe(
    candidates: Sequence[UniverseCandidate],
    *,
    as_of_date: date,
    thresholds: UniverseThresholds,
) -> list[UniverseFilterResult]:
    """Classify each candidate against SoT A6.1's universe conditions.

    Every condition is checked independently (no short-circuit), so a
    candidate violating multiple conditions carries every matching
    ``UniverseExclusionReason``. Boundary values (market cap / trading value
    exactly at the threshold, exactly ``min_listed_days`` days listed) are
    included — SoT A6.1 specifies ``>=``, not ``>``.
    """
    results: list[UniverseFilterResult] = []
    for candidate in candidates:
        reasons: list[UniverseExclusionReason] = []

        if candidate.market_cap is None:
            reasons.append(UniverseExclusionReason.MARKET_CAP_DATA_MISSING)
        elif candidate.market_cap < thresholds.market_cap_min:
            reasons.append(UniverseExclusionReason.MARKET_CAP_BELOW_MIN)

        if candidate.avg_trading_value_20d is None:
            reasons.append(UniverseExclusionReason.AVG_TRADING_VALUE_DATA_MISSING)
        elif candidate.avg_trading_value_20d < thresholds.avg_trading_value_min:
            reasons.append(UniverseExclusionReason.AVG_TRADING_VALUE_BELOW_MIN)

        # listed_at is None -> "unknown", included rather than excluded (see
        # module docstring's listed_at NULL policy).
        if candidate.listed_at is not None:
            listed_days = (as_of_date - candidate.listed_at).days
            if listed_days < thresholds.min_listed_days:
                reasons.append(UniverseExclusionReason.LISTED_LESS_THAN_MIN_DAYS)

        if candidate.is_managed:
            reasons.append(UniverseExclusionReason.MANAGED_ISSUE)

        if candidate.is_alert:
            reasons.append(UniverseExclusionReason.INVESTMENT_ALERT)

        if _is_preferred_stock(candidate.name):
            reasons.append(UniverseExclusionReason.PREFERRED_STOCK)

        results.append(
            UniverseFilterResult(
                asset_id=candidate.asset_id,
                included=not reasons,
                exclusion_reasons=reasons,
            )
        )
    return results
