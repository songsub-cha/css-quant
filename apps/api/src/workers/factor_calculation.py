"""Factor calculation orchestration (SoT A6.1 stage 2 — workers).

The lint-imports layer contract puts this here rather than in
``src/services``: ``src.services``' ``forbidden_modules`` includes
``src.engine`` (``apps/api/pyproject.toml``), so an orchestrator that calls
``src.engine.factor_calculation``/``src.engine.universe_filter``'s pure
functions cannot live in services. ``src.workers``' contract only forbids
``src.api``, so this module is the legal home — matching
``src.workers.universe_filter`` (issue #56/PR #57).

Registering ``calculate_factors`` as an actual Arq cron job and recording its
runs in ``job_runs`` is issue #39's scope — this module only provides the
callable pipeline: evaluate the universe (SoT A6.1 stage 1, inlined — see
below) -> fetch price/financial-statement history -> calculate every
included asset's factors -> upsert into ``asset_factors``.
"""

from __future__ import annotations

from datetime import date

from src.domain.asset import AssetRepository, AssetType, Market
from src.domain.asset_factor import AssetFactor, AssetFactorInfo, AssetFactorRepository
from src.domain.financial_statement import FinancialStatementRepository
from src.domain.market_price import MarketPriceRepository
from src.domain.universe_filter import UniverseCandidate, UniverseThresholds
from src.engine.factor_calculation import (
    calculate_liquidity,
    calculate_momentum,
    calculate_quality_factors,
    calculate_risk,
    calculate_value_factors,
    isolate_quarterly_income,
)
from src.engine.universe_filter import filter_universe

# SoT A6.1: 20-day average trading value — same window
# src.workers.universe_filter.evaluate_universe uses. Duplicated here
# (not imported from that module) because this worker inlines the
# universe-filter pipeline itself rather than calling evaluate_universe
# (see calculate_factors's docstring for why).
_AVG_TRADING_VALUE_WINDOW = 20

# Covers every price-based factor's window in one MarketPriceRepository.get_price_history
# call — the 52-week-high momentum factor needs the most (252 trading days).
_PRICE_HISTORY_WINDOW = 252


async def calculate_factors(
    asset_repo: AssetRepository,
    market_price_repo: MarketPriceRepository,
    financial_statement_repo: FinancialStatementRepository,
    asset_factor_repo: AssetFactorRepository,
    *,
    as_of_date: date,
    thresholds: UniverseThresholds,
) -> list[AssetFactor]:
    """Evaluate the universe, calculate every included asset's factors, and upsert.

    SoT A6.1 stage 1 (universe filter, issue #56) is inlined here rather
    than calling ``src.workers.universe_filter.evaluate_universe``: that
    function discards the ``UniverseCandidate`` snapshot
    (``market_cap``/``is_managed``/``is_alert``) it builds internally, but
    ``asset_factors`` needs exactly those values as its own universe-
    snapshot columns. Inlining the identical three-query fetch +
    ``filter_universe`` call reuses 100% of the same logic (same repository
    methods, same pure function) while keeping the snapshot instead of
    discarding it, avoiding both a duplicate query round trip and a second
    re-derivation.

    Only assets ``filter_universe`` includes get an ``asset_factors`` row —
    an excluded asset is skipped entirely rather than written with
    all-``None`` factors.
    """
    assets = await asset_repo.list_active(Market.KR, AssetType.STOCK)
    market_caps = await market_price_repo.get_market_caps(trade_date=as_of_date)
    avg_trading_values = await market_price_repo.get_avg_trading_value(
        as_of_date=as_of_date, window=_AVG_TRADING_VALUE_WINDOW
    )

    candidates = {
        asset.id: UniverseCandidate(
            asset_id=asset.id,
            name=asset.name,
            is_managed=asset.is_managed,
            is_alert=asset.is_alert,
            listed_at=asset.listed_at,
            market_cap=market_caps.get(asset.id),
            avg_trading_value_20d=avg_trading_values.get(asset.id),
        )
        for asset in assets
    }

    filter_results = filter_universe(
        list(candidates.values()), as_of_date=as_of_date, thresholds=thresholds
    )
    included_ids = [result.asset_id for result in filter_results if result.included]
    if not included_ids:
        return []

    price_history = await market_price_repo.get_price_history(
        asset_ids=included_ids, as_of_date=as_of_date, window=_PRICE_HISTORY_WINDOW
    )
    statement_history = await financial_statement_repo.get_statement_history(
        asset_ids=included_ids, as_of_date=as_of_date
    )

    factors: list[AssetFactor] = []
    for asset_id in included_ids:
        candidate = candidates[asset_id]
        bars = price_history.get(asset_id, [])
        momentum = calculate_momentum(bars)
        liquidity = calculate_liquidity(bars)
        risk = calculate_risk(bars)

        isolated_quarters = isolate_quarterly_income(statement_history.get(asset_id, []))
        quality = calculate_quality_factors(isolated_quarters)
        value = calculate_value_factors(
            market_cap=candidate.market_cap,
            net_income_ttm=quality.net_income_ttm,
            total_equity_latest=quality.total_equity_latest,
        )

        factor_info = AssetFactorInfo(
            asset_id=asset_id,
            factor_date=as_of_date,
            momentum_3m=momentum.momentum_3m,
            momentum_6m=momentum.momentum_6m,
            dist_52w_high=momentum.dist_52w_high,
            ma20_deviation=momentum.ma20_deviation,
            roe=quality.roe,
            op_margin=quality.op_margin,
            revenue_growth_yoy=quality.revenue_growth_yoy,
            debt_ratio=quality.debt_ratio,
            per=value.per,
            pbr=value.pbr,
            avg_trading_value_20d=avg_trading_values.get(asset_id),
            volume_cv=liquidity.volume_cv,
            volatility_60d=risk.volatility_60d,
            mdd_60d=risk.mdd_60d,
            gap_frequency_60d=risk.gap_frequency_60d,
            market_cap=candidate.market_cap,
            is_managed=candidate.is_managed,
            is_alert=candidate.is_alert,
            financial_data_as_of=quality.financial_data_as_of,
        )
        factors.append(await asset_factor_repo.upsert(factor=factor_info))

    return factors
