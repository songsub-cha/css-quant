"""Universe filter orchestration (SoT A6.1 — workers).

The lint-imports layer contract puts this here rather than in
``src/services``: ``src.services``' ``forbidden_modules`` includes
``src.engine`` (``apps/api/pyproject.toml``), so an orchestrator that calls
``src.engine.universe_filter.filter_universe``'s pure judgement cannot live
in services. ``src.workers``' contract only forbids ``src.api``, so this
module is the legal home — matching ``src.workers.market_regime_detection``
(issue #54/PR #55).

Registering ``evaluate_universe`` as an actual Arq cron job and recording its
runs in ``job_runs`` is issue #39's scope — this module only provides the
callable pipeline: list active KR STOCK assets -> fetch market cap / 20-day
average trading value -> judge.
"""

from __future__ import annotations

from datetime import date

from src.domain.asset import AssetRepository, AssetType, Market
from src.domain.market_price import MarketPriceRepository
from src.domain.universe_filter import (
    UniverseCandidate,
    UniverseFilterResult,
    UniverseThresholds,
)
from src.engine.universe_filter import filter_universe

# SoT A6.1: 20-day average trading value. Not part of UniverseThresholds
# (that carries only the configurable cutoff amounts) — this is the fixed
# window size the average is computed over, same role as
# market_regime_detection's _VKOSPI_AVG_WINDOW.
_AVG_TRADING_VALUE_WINDOW = 20


async def evaluate_universe(
    asset_repo: AssetRepository,
    market_price_repo: MarketPriceRepository,
    *,
    as_of_date: date,
    thresholds: UniverseThresholds,
) -> list[UniverseFilterResult]:
    """Fetch one trading day's candidate pool and judge it against SoT A6.1.

    ``asset_repo.list_active(Market.KR, AssetType.STOCK)`` is the candidate
    selection itself — ETF, inactive rows, and non-KR assets never become a
    ``UniverseCandidate``. Both market-price queries are bounded to
    ``as_of_date`` (point-in-time, no look-ahead) — see
    ``MarketPriceRepository.get_market_caps``/``get_avg_trading_value``'s
    docstrings.
    """
    assets = await asset_repo.list_active(Market.KR, AssetType.STOCK)
    market_caps = await market_price_repo.get_market_caps(trade_date=as_of_date)
    avg_trading_values = await market_price_repo.get_avg_trading_value(
        as_of_date=as_of_date, window=_AVG_TRADING_VALUE_WINDOW
    )

    candidates = [
        UniverseCandidate(
            asset_id=asset.id,
            name=asset.name,
            is_managed=asset.is_managed,
            is_alert=asset.is_alert,
            listed_at=asset.listed_at,
            market_cap=market_caps.get(asset.id),
            avg_trading_value_20d=avg_trading_values.get(asset.id),
        )
        for asset in assets
    ]

    return filter_universe(candidates, as_of_date=as_of_date, thresholds=thresholds)
