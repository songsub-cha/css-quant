"""Ticker master schema + data source port (SoT C1 — domain).

``DataSource`` is the port ``src.services``/``src.workers`` will depend on
once the collection pipeline is wired up (a later issue). It lives here —
rather than alongside its concrete implementation in
``src/adapters/data_sources.py`` — for the same reason as
``UserRepository`` (see ``src/domain/user.py``): callers elsewhere in the
codebase need the type for typed parameters, but the import-linter contract
forbids most layers from importing ``src.adapters`` directly. Every layer is
already allowed to import ``domain``, so the port lives here and
implementations satisfy it structurally (Python ``Protocol``, no explicit
inheritance).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Exchange(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class TickerInfo(BaseModel):
    """External-facing representation of a single listed ticker."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    name: str
    exchange: Exchange


class DataSource(Protocol):
    """Port for ticker-master collection, selected via a future adapter env var.

    Real implementations (``PykrxDataSource``, with a KRX 정보데이터시스템
    fallback) are added in a later issue behind this same interface — SoT
    B3's fake-by-default pattern, matching ``LLMClient``/``FakeLLMClient``.
    """

    async def list_tickers(self) -> list[TickerInfo]: ...
