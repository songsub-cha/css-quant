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
from datetime import UTC, datetime
from uuid import UUID

from src.domain.asset import Asset, AssetType, Exchange, Market
from src.domain.financial_statement import FinancialStatement, FinancialStatementInfo
from src.domain.ids import generate_uuid7
from src.domain.index_price import IndexPrice, IndexPriceInfo
from src.domain.market_price import DailyPriceInfo, MarketPrice
from src.domain.password_reset import PasswordResetToken
from src.domain.user import User

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
