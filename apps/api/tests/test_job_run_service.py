"""``start_job_run``/``finish_job_run`` (SoT C4, services layer).

No DB container in this environment: exercised against an in-memory fake
repository, the same isolation approach ``test_asset_sync.py`` uses for its
repository port. Uses ``asyncio.run`` directly (no pytest-asyncio dependency
in this project) — same pattern as ``test_asset_sync.py``.

``FakeJobRunRepository`` lives in ``conftest.py`` — promoted from a local
definition here once ``test_quality_gate_worker.py`` (issue #60) also needed
it. ``test_job_run_repository.py`` exercises the real SQLAlchemy
implementation against a migrated Postgres container instead.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.domain.job_run import JobRunStatus
from src.services.job_run import finish_job_run, start_job_run

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
