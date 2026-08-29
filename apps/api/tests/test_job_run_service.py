"""``start_job_run``/``finish_job_run``/``run_locked_job`` (SoT C4, services layer).

No DB container in this environment: exercised against an in-memory fake
repository, the same isolation approach ``test_asset_sync.py`` uses for its
repository port. Uses ``asyncio.run`` directly (no pytest-asyncio dependency
in this project) — same pattern as ``test_asset_sync.py``.

``FakeJobRunRepository`` lives in ``conftest.py`` — promoted from a local
definition here once ``test_quality_gate_worker.py`` (issue #60) also needed
it. ``test_job_run_repository.py``/``test_job_lock.py`` exercise the real
SQLAlchemy/Redis implementations against real containers instead.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from src.domain.job_run import JobRunStatus
from src.services.job_run import finish_job_run, run_locked_job, start_job_run

from .conftest import FakeJobRunRepository


def test_start_job_run_creates_running_row() -> None:
    repo = FakeJobRunRepository()

    row = asyncio.run(start_job_run(repo, job_name="sync_assets", run_date=date(2026, 7, 29)))

    assert row.status == JobRunStatus.RUNNING
    assert len(repo.runs) == 1


def test_finish_job_run_round_trips_to_success() -> None:
    repo = FakeJobRunRepository()
    started = asyncio.run(start_job_run(repo, job_name="sync_assets", run_date=date(2026, 7, 29)))

    finished = asyncio.run(
        finish_job_run(repo, started.id, status=JobRunStatus.SUCCESS, stats={"synced": 10})
    )

    assert finished.status == JobRunStatus.SUCCESS
    assert finished.stats == {"synced": 10}
    assert finished.finished_at is not None


def test_finish_job_run_rejects_running_status() -> None:
    repo = FakeJobRunRepository()
    started = asyncio.run(start_job_run(repo, job_name="sync_assets", run_date=date(2026, 7, 29)))

    with pytest.raises(ValueError):
        asyncio.run(finish_job_run(repo, started.id, status=JobRunStatus.RUNNING))


class _FakeJobLock:
    """In-memory stand-in for ``JobLock`` — tracks held keys and their tokens."""

    def __init__(self, *, held: dict[str, str] | None = None) -> None:
        self._held: dict[str, str] = held or {}

    async def acquire(self, key: str, *, ttl_seconds: int) -> str | None:
        if key in self._held:
            return None
        token = f"token-{len(self._held)}"
        self._held[key] = token
        return token

    async def release(self, key: str, token: str) -> None:
        if self._held.get(key) == token:
            del self._held[key]


def test_run_locked_job_records_success_and_releases_lock() -> None:
    repo = FakeJobRunRepository()
    lock = _FakeJobLock()

    async def _work() -> dict[str, Any]:
        return {"synced": 3}

    result = asyncio.run(
        run_locked_job(
            repo,
            lock,
            job_name="sync_assets",
            run_date=date(2026, 7, 29),
            lock_ttl_seconds=60,
            work=_work,
        )
    )

    assert result is not None
    assert result.status == JobRunStatus.SUCCESS
    assert result.stats == {"synced": 3}
    assert len(repo.runs) == 1
    assert lock._held == {}


def test_run_locked_job_skips_when_lock_already_held() -> None:
    repo = FakeJobRunRepository()
    lock = _FakeJobLock(held={"job_lock:sync_assets:2026-07-29": "someone-else"})

    async def _work() -> dict[str, Any]:
        raise AssertionError("work() must not run when the lock is already held")

    result = asyncio.run(
        run_locked_job(
            repo,
            lock,
            job_name="sync_assets",
            run_date=date(2026, 7, 29),
            lock_ttl_seconds=60,
            work=_work,
        )
    )

    assert result is None
    assert repo.runs == []


def test_run_locked_job_records_failure_and_does_not_propagate() -> None:
    repo = FakeJobRunRepository()
    lock = _FakeJobLock()

    async def _work() -> dict[str, Any]:
        raise RuntimeError("data source timed out")

    result = asyncio.run(
        run_locked_job(
            repo,
            lock,
            job_name="collect_prices",
            run_date=date(2026, 7, 29),
            lock_ttl_seconds=60,
            work=_work,
        )
    )

    assert result is not None
    assert result.status == JobRunStatus.FAILED
    assert result.error == "data source timed out"
    assert lock._held == {}
