"""Test-collection env scaffolding + shared fakes.

``Settings.cookie_secure`` (SoT D2) has no default on purpose — every
deployment must set it explicitly. But two modules build a module-level
``Settings()`` at *import* time: ``src/workers/settings.py`` (imported by
``tests/test_worker_settings.py``) and ``alembic/env.py``. Without
``COOKIE_SECURE`` present in the environment before those imports happen,
pytest collection itself fails with a ``ValidationError`` before any test
runs. ``secret_key`` (added for JWT issuance, SoT D2/B4.6) has the same
import-time-required shape, plus a ``min_length=32`` floor — the dummy value
below satisfies it.

pytest imports ``conftest.py`` ahead of collecting test modules in the same
directory tree, so setting the env vars here (rather than in a fixture,
which would run too late) is what makes collection succeed. This is
test-process scaffolding only — real deployments must still set these
explicitly via ``.env`` (dev/prod compose ``env_file``); nothing here
weakens that requirement.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.domain.ai_score import AssetScore, AssetScoreInfo
from src.domain.asset import Asset, AssetType, Exchange, Market
from src.domain.asset_factor import AssetFactor, AssetFactorInfo
from src.domain.financial_statement import (
    DisclosedStatement,
    FinancialStatement,
    FinancialStatementInfo,
)
from src.domain.ids import generate_uuid7
from src.domain.index_price import IndexCode, IndexPrice, IndexPriceInfo
from src.domain.job_run import JobRun, JobRunStatus
from src.domain.llm_explanation import LLMExplanationResult
from src.domain.market_price import DailyPriceInfo, MarketPrice, PriceBar, PriceCheckBar
from src.domain.market_regime import MarketRegime, MarketRegimeInfo
from src.domain.password_reset import PasswordResetToken
from src.domain.strategy import Strategy, StrategyInfo, StrategyStatus
from src.domain.user import User
from src.domain.watchlist import WatchlistItem, WatchlistItemInfo, WatchlistKind

os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-prod-use-000")


class FakeUserRepository:
    """In-memory ``UserRepository`` (SoT domain protocol) — no DB container in this environment.

    Shared by every auth test module (bootstrap, login, ``get_current_user``)
    the same way ``FakeLLMClient`` (src/adapters/llm.py) stands in for a real
    external adapter.
    """

    def __init__(self) -> None:
        self.users: list[User] = []

    async def exists_any(self) -> bool:
        return bool(self.users)

    async def create(self, *, email: str, password_hash: str) -> User:
        now = datetime.now(UTC)
        user = User(
            id=generate_uuid7(),
            email=email,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )
        self.users.append(user)
        return user

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.users if u.email == email), None)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return next((u for u in self.users if u.id == user_id), None)

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> None:
        user = next((u for u in self.users if u.id == user_id), None)
        if user is not None:
            user.password_hash = password_hash


class FakeAssetRepository:
    """In-memory ``AssetRepository`` — same role as ``FakeUserRepository``.

    Mirrors ``SqlAlchemyAssetRepository``'s "active rows only" scoping (SoT
    C3): a relisted ticker's old inactive row is never matched or mutated,
    only ever left in ``self.assets`` for a later query to see.
    """

    def __init__(self) -> None:
        self.assets: list[Asset] = []

    async def get_active_by_ticker(self, ticker: str, market: Market) -> Asset | None:
        return next(
            (a for a in self.assets if a.ticker == ticker and a.market == market and a.is_active),
            None,
        )

    async def list_active(self, market: Market, asset_type: AssetType) -> list[Asset]:
        return [
            a
            for a in self.assets
            if a.market == market and a.asset_type == asset_type and a.is_active
        ]

    async def list_by_ids(self, asset_ids: Sequence[UUID]) -> list[Asset]:
        asset_id_set = set(asset_ids)
        return [a for a in self.assets if a.id in asset_id_set]

    async def upsert_active(
        self,
        *,
        ticker: str,
        name: str,
        market: Market,
        asset_type: AssetType,
        exchange: Exchange,
    ) -> Asset:
        existing = await self.get_active_by_ticker(ticker, market)
        if existing is not None:
            existing.name = name
            existing.asset_type = asset_type
            existing.exchange = exchange
            return existing

        now = datetime.now(UTC)
        asset = Asset(
            id=generate_uuid7(),
            ticker=ticker,
            name=name,
            market=market,
            asset_type=asset_type,
            exchange=exchange,
            is_active=True,
            is_managed=False,
            is_alert=False,
            created_at=now,
            updated_at=now,
        )
        self.assets.append(asset)
        return asset


class FakeMarketPriceRepository:
    """In-memory ``MarketPriceRepository`` — same role as ``FakeAssetRepository``.

    Mirrors ``SqlAlchemyMarketPriceRepository``'s ``(asset_id, date)``
    in-place update semantics: re-upserting the same key updates the
    existing row rather than appending a duplicate.
    """

    def __init__(self) -> None:
        self.prices: list[MarketPrice] = []

    async def upsert(self, *, asset_id: UUID, bar: DailyPriceInfo) -> MarketPrice:
        existing = next(
            (p for p in self.prices if p.asset_id == asset_id and p.date == bar.date), None
        )
        if existing is not None:
            existing.open = bar.open
            existing.high = bar.high
            existing.low = bar.low
            existing.close = bar.close
            existing.adjusted_close = bar.adjusted_close
            existing.volume = bar.volume
            existing.trading_value = bar.trading_value
            existing.market_cap = bar.market_cap
            existing.halted = bar.halted
            return existing

        row = MarketPrice(
            asset_id=asset_id,
            date=bar.date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            adjusted_close=bar.adjusted_close,
            volume=bar.volume,
            trading_value=bar.trading_value,
            market_cap=bar.market_cap,
            halted=bar.halted,
        )
        self.prices.append(row)
        return row

    async def get_market_caps(self, *, trade_date: date) -> dict[UUID, Decimal | None]:
        return {p.asset_id: p.market_cap for p in self.prices if p.date == trade_date}

    async def get_avg_trading_value(self, *, as_of_date: date, window: int) -> dict[UUID, Decimal]:
        # Mirrors SqlAlchemyMarketPriceRepository.get_avg_trading_value's
        # point-in-time semantics: bound to as_of_date first, then pick the
        # `window` most recent *actual* trading dates within that bound.
        eligible_dates = sorted({p.date for p in self.prices if p.date <= as_of_date}, reverse=True)
        recent_dates = set(eligible_dates[:window]) if window > 0 else set()

        by_asset: dict[UUID, list[Decimal]] = {}
        for p in self.prices:
            if p.date in recent_dates:
                by_asset.setdefault(p.asset_id, []).append(p.trading_value)

        return {
            asset_id: sum(values, start=Decimal(0)) / len(values)
            for asset_id, values in by_asset.items()
        }

    async def get_price_checks(self, *, trade_date: date) -> dict[UUID, PriceCheckBar]:
        return {
            p.asset_id: PriceCheckBar(close=p.close, high=p.high, low=p.low)
            for p in self.prices
            if p.date == trade_date
        }

    async def get_price_history(
        self, *, asset_ids: Sequence[UUID], as_of_date: date, window: int
    ) -> dict[UUID, list[PriceBar]]:
        # Mirrors SqlAlchemyMarketPriceRepository.get_price_history: recent
        # trading dates are market-wide (not per-asset), bounded to
        # as_of_date first, then the `window` most recent actual dates.
        if not asset_ids:
            return {}
        asset_id_set = set(asset_ids)
        eligible_dates = sorted({p.date for p in self.prices if p.date <= as_of_date}, reverse=True)
        recent_dates = set(eligible_dates[:window]) if window > 0 else set()

        by_asset: dict[UUID, list[PriceBar]] = {}
        for p in sorted(self.prices, key=lambda p: p.date):
            if p.asset_id in asset_id_set and p.date in recent_dates:
                by_asset.setdefault(p.asset_id, []).append(
                    PriceBar(
                        date=p.date,
                        open=p.open,
                        high=p.high,
                        low=p.low,
                        close=p.close,
                        adjusted_close=p.adjusted_close,
                        volume=p.volume,
                        trading_value=p.trading_value,
                        halted=p.halted,
                    )
                )
        return by_asset


class FakeIndexPriceRepository:
    """In-memory ``IndexPriceRepository`` — same role as ``FakeMarketPriceRepository``.

    Mirrors ``SqlAlchemyIndexPriceRepository``'s ``(index_code, date)``
    in-place update semantics: re-upserting the same key updates the
    existing row rather than appending a duplicate.
    """

    def __init__(self) -> None:
        self.prices: list[IndexPrice] = []

    async def upsert(self, *, bar: IndexPriceInfo) -> IndexPrice:
        existing = next(
            (p for p in self.prices if p.index_code == bar.index_code and p.date == bar.date),
            None,
        )
        if existing is not None:
            existing.open = bar.open
            existing.high = bar.high
            existing.low = bar.low
            existing.close = bar.close
            existing.volume = bar.volume
            existing.trading_value = bar.trading_value
            return existing

        row = IndexPrice(
            index_code=bar.index_code,
            date=bar.date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            trading_value=bar.trading_value,
        )
        self.prices.append(row)
        return row

    async def get_recent(
        self, *, index_code: IndexCode, end_date: date, limit: int
    ) -> list[IndexPriceInfo]:
        matching = sorted(
            (p for p in self.prices if p.index_code == index_code and p.date <= end_date),
            key=lambda p: p.date,
        )
        window = matching[-limit:] if limit > 0 else []
        return [
            IndexPriceInfo(
                index_code=p.index_code,
                date=p.date,
                open=p.open,
                high=p.high,
                low=p.low,
                close=p.close,
                volume=p.volume,
                trading_value=p.trading_value,
            )
            for p in window
        ]


class FakeMarketRegimeRepository:
    """In-memory ``MarketRegimeRepository`` — same role as ``FakeIndexPriceRepository``.

    Mirrors ``SqlAlchemyMarketRegimeRepository``'s ``regime_date`` in-place
    update semantics: re-upserting the same key updates the existing row
    rather than appending a duplicate.
    """

    def __init__(self) -> None:
        self.regimes: list[MarketRegime] = []

    async def upsert(self, *, regime: MarketRegimeInfo) -> MarketRegime:
        existing = next(
            (r for r in self.regimes if r.regime_date == regime.regime_date), None
        )
        if existing is not None:
            existing.regime = regime.regime
            existing.kospi_close = regime.kospi_close
            existing.kospi_ma200 = regime.kospi_ma200
            existing.vkospi = regime.vkospi
            existing.kospi_volatility_20d = regime.kospi_volatility_20d
            existing.market_shock = regime.market_shock
            existing.signals = regime.signals
            return existing

        row = MarketRegime(
            regime_date=regime.regime_date,
            regime=regime.regime,
            kospi_close=regime.kospi_close,
            kospi_ma200=regime.kospi_ma200,
            vkospi=regime.vkospi,
            kospi_volatility_20d=regime.kospi_volatility_20d,
            market_shock=regime.market_shock,
            signals=regime.signals,
        )
        self.regimes.append(row)
        return row

    async def get_recent(self, *, before_date: date, limit: int) -> list[MarketRegime]:
        matching = sorted(
            (r for r in self.regimes if r.regime_date < before_date),
            key=lambda r: r.regime_date,
            reverse=True,
        )
        return matching[:limit] if limit > 0 else []

    async def get_by_date(self, *, regime_date: date) -> MarketRegime | None:
        return next((r for r in self.regimes if r.regime_date == regime_date), None)


class FakeFinancialStatementRepository:
    """In-memory ``FinancialStatementRepository`` — same role as ``FakeIndexPriceRepository``.

    Mirrors ``SqlAlchemyFinancialStatementRepository``'s
    ``(asset_id, fiscal_year, fiscal_quarter)`` in-place update semantics,
    including a 정정공시 replacing ``rcept_no``/``disclosed_at``/line items
    on an already-existing row.
    """

    def __init__(self) -> None:
        self.statements: list[FinancialStatement] = []

    async def upsert(
        self, *, asset_id: UUID, statement: FinancialStatementInfo
    ) -> FinancialStatement:
        existing = next(
            (
                s
                for s in self.statements
                if s.asset_id == asset_id
                and s.fiscal_year == statement.fiscal_year
                and s.fiscal_quarter == statement.fiscal_quarter
            ),
            None,
        )
        if existing is not None:
            existing.consolidated_type = statement.consolidated_type
            existing.revenue = statement.revenue
            existing.operating_income = statement.operating_income
            existing.net_income = statement.net_income
            existing.total_assets = statement.total_assets
            existing.total_liabilities = statement.total_liabilities
            existing.total_equity = statement.total_equity
            existing.disclosed_at = statement.disclosed_at
            existing.rcept_no = statement.rcept_no
            return existing

        row = FinancialStatement(
            asset_id=asset_id,
            fiscal_year=statement.fiscal_year,
            fiscal_quarter=statement.fiscal_quarter,
            consolidated_type=statement.consolidated_type,
            revenue=statement.revenue,
            operating_income=statement.operating_income,
            net_income=statement.net_income,
            total_assets=statement.total_assets,
            total_liabilities=statement.total_liabilities,
            total_equity=statement.total_equity,
            disclosed_at=statement.disclosed_at,
            rcept_no=statement.rcept_no,
        )
        self.statements.append(row)
        return row

    async def get_statement_history(
        self, *, asset_ids: Sequence[UUID], as_of_date: date
    ) -> dict[UUID, list[DisclosedStatement]]:
        # Mirrors SqlAlchemyFinancialStatementRepository.get_statement_history's
        # disclosed_at <= as_of_date bound (SoT A6.7.2 look-ahead prevention).
        if not asset_ids:
            return {}
        asset_id_set = set(asset_ids)
        by_asset: dict[UUID, list[DisclosedStatement]] = {}
        for s in self.statements:
            if s.asset_id in asset_id_set and s.disclosed_at <= as_of_date:
                by_asset.setdefault(s.asset_id, []).append(
                    DisclosedStatement(
                        fiscal_year=s.fiscal_year,
                        fiscal_quarter=s.fiscal_quarter,
                        revenue=s.revenue,
                        operating_income=s.operating_income,
                        net_income=s.net_income,
                        total_assets=s.total_assets,
                        total_liabilities=s.total_liabilities,
                        total_equity=s.total_equity,
                        disclosed_at=s.disclosed_at,
                    )
                )
        return by_asset


class FakeAssetFactorRepository:
    """In-memory ``AssetFactorRepository`` — same role as ``FakeIndexPriceRepository``.

    Mirrors ``SqlAlchemyAssetFactorRepository``'s ``(asset_id, factor_date)``
    in-place update semantics: re-upserting the same key updates the
    existing row rather than appending a duplicate.
    """

    def __init__(self) -> None:
        self.factors: list[AssetFactor] = []

    async def upsert(self, *, factor: AssetFactorInfo) -> AssetFactor:
        existing = next(
            (
                f
                for f in self.factors
                if f.asset_id == factor.asset_id and f.factor_date == factor.factor_date
            ),
            None,
        )
        if existing is not None:
            existing.momentum_3m = factor.momentum_3m
            existing.momentum_6m = factor.momentum_6m
            existing.dist_52w_high = factor.dist_52w_high
            existing.ma20_deviation = factor.ma20_deviation
            existing.roe = factor.roe
            existing.op_margin = factor.op_margin
            existing.revenue_growth_yoy = factor.revenue_growth_yoy
            existing.debt_ratio = factor.debt_ratio
            existing.per = factor.per
            existing.pbr = factor.pbr
            existing.avg_trading_value_20d = factor.avg_trading_value_20d
            existing.volume_cv = factor.volume_cv
            existing.volatility_60d = factor.volatility_60d
            existing.mdd_60d = factor.mdd_60d
            existing.gap_frequency_60d = factor.gap_frequency_60d
            existing.market_cap = factor.market_cap
            existing.is_managed = factor.is_managed
            existing.is_alert = factor.is_alert
            existing.financial_data_as_of = factor.financial_data_as_of
            return existing

        row = AssetFactor(
            asset_id=factor.asset_id,
            factor_date=factor.factor_date,
            momentum_3m=factor.momentum_3m,
            momentum_6m=factor.momentum_6m,
            dist_52w_high=factor.dist_52w_high,
            ma20_deviation=factor.ma20_deviation,
            roe=factor.roe,
            op_margin=factor.op_margin,
            revenue_growth_yoy=factor.revenue_growth_yoy,
            debt_ratio=factor.debt_ratio,
            per=factor.per,
            pbr=factor.pbr,
            avg_trading_value_20d=factor.avg_trading_value_20d,
            volume_cv=factor.volume_cv,
            volatility_60d=factor.volatility_60d,
            mdd_60d=factor.mdd_60d,
            gap_frequency_60d=factor.gap_frequency_60d,
            market_cap=factor.market_cap,
            is_managed=factor.is_managed,
            is_alert=factor.is_alert,
            financial_data_as_of=factor.financial_data_as_of,
        )
        self.factors.append(row)
        return row

    async def get_by_factor_date(self, *, factor_date: date) -> list[AssetFactor]:
        return [f for f in self.factors if f.factor_date == factor_date]


class FakeAssetScoreRepository:
    """In-memory ``AssetScoreRepository`` — same role as ``FakeAssetFactorRepository``.

    Mirrors ``SqlAlchemyAssetScoreRepository``'s ``(asset_id, score_date)``
    in-place update semantics: re-upserting the same key updates the
    existing row rather than appending a duplicate.
    """

    def __init__(self) -> None:
        self.scores: list[AssetScore] = []

    async def upsert(self, *, score: AssetScoreInfo) -> AssetScore:
        existing = next(
            (
                s
                for s in self.scores
                if s.asset_id == score.asset_id and s.score_date == score.score_date
            ),
            None,
        )
        if existing is not None:
            existing.regime = score.regime
            existing.total_score = score.total_score
            existing.momentum_score = score.momentum_score
            existing.quality_score = score.quality_score
            existing.value_score = score.value_score
            existing.liquidity_score = score.liquidity_score
            existing.risk_score = score.risk_score
            existing.summary = score.summary
            existing.positive_reasons = score.positive_reasons
            existing.risk_reasons = score.risk_reasons
            existing.llm_model = score.llm_model
            existing.llm_generated_at = score.llm_generated_at
            return existing

        row = AssetScore(
            asset_id=score.asset_id,
            score_date=score.score_date,
            regime=score.regime,
            total_score=score.total_score,
            momentum_score=score.momentum_score,
            quality_score=score.quality_score,
            value_score=score.value_score,
            liquidity_score=score.liquidity_score,
            risk_score=score.risk_score,
            summary=score.summary,
            positive_reasons=score.positive_reasons,
            risk_reasons=score.risk_reasons,
            llm_model=score.llm_model,
            llm_generated_at=score.llm_generated_at,
        )
        self.scores.append(row)
        return row

    async def get_by_date(self, *, score_date: date) -> list[AssetScore]:
        return [s for s in self.scores if s.score_date == score_date]

    async def get_latest_score_date(self) -> date | None:
        dates = {s.score_date for s in self.scores}
        return max(dates) if dates else None


class FakeLLMExplanationCache:
    """In-memory ``LLMExplanationCache`` — same role as ``FakeIndexPriceRepository``.

    Ignores ``ttl_seconds`` (no expiry) — tests only assert hit/miss
    behavior, never TTL expiry (that is ``RedisLLMExplanationCache``'s to
    exercise against a real Redis container).
    """

    def __init__(self) -> None:
        self._entries: dict[str, LLMExplanationResult] = {}

    async def get(self, key: str) -> LLMExplanationResult | None:
        return self._entries.get(key)

    async def set(self, key: str, result: LLMExplanationResult, *, ttl_seconds: int) -> None:
        self._entries[key] = result


class FakePasswordResetTokenRepository:
    """In-memory ``PasswordResetTokenRepository`` — same role as ``FakeUserRepository``."""

    def __init__(self) -> None:
        self.tokens: list[PasswordResetToken] = []

    async def create(
        self, *, user_id: UUID, token_hash: str, expires_at: datetime
    ) -> PasswordResetToken:
        token = PasswordResetToken(
            id=generate_uuid7(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            used_at=None,
            created_at=datetime.now(UTC),
        )
        self.tokens.append(token)
        return token

    async def use_token(self, token_hash: str, *, now: datetime) -> UUID | None:
        token = next(
            (
                t
                for t in self.tokens
                if t.token_hash == token_hash and t.used_at is None and t.expires_at > now
            ),
            None,
        )
        if token is None:
            return None
        token.used_at = now
        return token.user_id


class FakeJobRunRepository:
    """In-memory ``JobRunRepository`` — same role as ``FakeUserRepository``.

    Promoted from ``test_job_run_service.py``'s local ``_FakeJobRunRepository``
    (its original docstring: "다른 테스트 모듈이 필요해지면 승격") now that
    ``test_quality_gate_worker.py`` needs it too.
    """

    def __init__(self) -> None:
        self.runs: list[JobRun] = []

    async def start(self, *, job_name: str, run_date: date) -> JobRun:
        row = JobRun(
            id=generate_uuid7(),
            job_name=job_name,
            run_date=run_date,
            status=JobRunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        self.runs.append(row)
        return row

    async def finish(
        self,
        job_run_id: UUID,
        *,
        status: JobRunStatus,
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> JobRun:
        row = next(r for r in self.runs if r.id == job_run_id)
        row.status = status
        row.finished_at = datetime.now(UTC)
        row.error = error
        row.stats = stats
        return row


class FakeWatchlistItemRepository:
    """In-memory ``WatchlistItemRepository`` — same role as ``FakeAssetScoreRepository``.

    Mirrors ``SqlAlchemyWatchlistItemRepository``'s ``(user_id, asset_id)``
    in-place update semantics: re-upserting the same pair updates the
    existing row's ``kind``/``note`` rather than appending a duplicate.
    """

    def __init__(self) -> None:
        self.items: list[WatchlistItem] = []

    def _find(self, *, user_id: UUID, asset_id: UUID) -> WatchlistItem | None:
        return next(
            (i for i in self.items if i.user_id == user_id and i.asset_id == asset_id),
            None,
        )

    async def upsert(self, *, item: WatchlistItemInfo) -> WatchlistItem:
        existing = self._find(user_id=item.user_id, asset_id=item.asset_id)
        if existing is not None:
            existing.kind = item.kind
            existing.note = item.note
            return existing

        now = datetime.now(UTC)
        row = WatchlistItem(
            id=generate_uuid7(),
            user_id=item.user_id,
            asset_id=item.asset_id,
            kind=item.kind,
            note=item.note,
            created_at=now,
            updated_at=now,
        )
        self.items.append(row)
        return row

    async def remove(self, *, user_id: UUID, asset_id: UUID) -> None:
        existing = self._find(user_id=user_id, asset_id=asset_id)
        if existing is not None:
            self.items.remove(existing)

    async def list_by_user(
        self, *, user_id: UUID, kind: WatchlistKind | None = None
    ) -> list[WatchlistItem]:
        return [
            i for i in self.items if i.user_id == user_id and (kind is None or i.kind == kind)
        ]


class FakeStrategyRepository:
    """In-memory ``StrategyRepository`` — same role as ``FakeWatchlistItemRepository``.

    ``get_by_id``/``list_by_user`` mirror ``SqlAlchemyStrategyRepository``'s
    ``deleted_at IS NULL`` filtering (SoT B4.10 soft delete) and user
    scoping (IDOR guard). ``update``/``soft_delete`` mutate the same object
    reference already in ``self.strategies`` — no session to commit against.
    """

    def __init__(self) -> None:
        self.strategies: list[Strategy] = []

    async def create(self, *, info: StrategyInfo) -> Strategy:
        now = datetime.now(UTC)
        row = Strategy(
            id=generate_uuid7(),
            user_id=info.user_id,
            name=info.name,
            description=info.description,
            status=StrategyStatus.DRAFT,
            execution_mode=info.execution_mode,
            config=info.config,
            version=1,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
        self.strategies.append(row)
        return row

    async def get_by_id(self, *, user_id: UUID, strategy_id: UUID) -> Strategy | None:
        return next(
            (
                s
                for s in self.strategies
                if s.id == strategy_id and s.user_id == user_id and s.deleted_at is None
            ),
            None,
        )

    async def list_by_user(
        self, *, user_id: UUID, status: StrategyStatus | None = None
    ) -> list[Strategy]:
        return [
            s
            for s in self.strategies
            if s.user_id == user_id
            and s.deleted_at is None
            and (status is None or s.status == status)
        ]

    async def update(self, strategy: Strategy) -> Strategy:
        return strategy

    async def soft_delete(self, strategy: Strategy) -> None:
        strategy.deleted_at = datetime.now(UTC)
