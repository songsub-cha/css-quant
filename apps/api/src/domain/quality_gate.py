"""Data quality gate DTOs (SoT A6.4/A2 원칙 8 — domain).

A6.4 requires four checks immediately before score/signal generation:
freshness (today's prices exist), coverage (>=98% of the candidate pool has
today's bar), integrity (no non-positive close/high<low/±30%+ moves), and
indicator (KOSPI 200-day MA is computable). A gate-wide failure must halt the
day fail-closed (SoT A2 원칙 8) rather than degrade silently — the individual
per-check results below are what ``job_runs.stats`` stores as evidence.

No new table is added here — the result is recorded into the existing
``job_runs.stats`` JSONB column (SoT C4), per the plan's rationale that
``job_run.py``'s forward-reference docstring already points at this. These
DTOs are ``src.engine.quality_gate.judge_quality_gate``'s pure input/output
shape, the same role ``UniverseThresholds``/``UniverseFilterResult`` play for
``src.engine.universe_filter.filter_universe``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class QualityCheckName(StrEnum):
    FRESHNESS = "FRESHNESS"
    COVERAGE = "COVERAGE"
    INTEGRITY = "INTEGRITY"
    INDICATOR = "INDICATOR"


class QualityGateThresholds(BaseModel):
    """Configurable cutoffs (SoT A6.4) — sourced from ``config.Settings``, never hardcoded."""

    model_config = ConfigDict(frozen=True)

    coverage_min_pct: Decimal
    max_price_move_pct: Decimal


class QualityCheckResult(BaseModel):
    """One check's verdict + JSON-safe diagnostic detail.

    ``details`` only ever holds values that survive a round trip through
    ``job_runs.stats`` (JSONB) unchanged — floats/ints/strs/bools/None, never
    ``Decimal``/``UUID`` directly — the same convention
    ``detect_market_shock``'s ``signals`` dict follows (``float()``-cast
    Decimals, ``str()``-cast UUIDs).
    """

    model_config = ConfigDict(frozen=True)

    name: QualityCheckName
    passed: bool
    details: dict[str, Any]


class QualityGateResult(BaseModel):
    """Whole-gate verdict for one trading day — ``passed`` iff every check passed.

    ``src.workers.quality_gate.evaluate_quality_gate`` builds this from
    ``src.engine.quality_gate.judge_quality_gate``'s output and records it
    into ``job_runs.stats`` via ``src.services.job_run.finish_job_run``.
    """

    model_config = ConfigDict(frozen=True)

    gate_date: date
    passed: bool
    checks: list[QualityCheckResult]
