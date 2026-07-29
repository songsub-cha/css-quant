"""``start_job_run``/``finish_job_run`` (SoT C4, services layer).

No DB container in this environment: exercised against an in-memory fake
repository, the same isolation approach ``test_asset_sync.py`` uses for its
repository port. Uses ``asyncio.run`` directly (no pytest-asyncio dependency
in this project) — same pattern as ``test_asset_sync.py``.

The fake lives here rather than in ``conftest.py`` because, unlike
``FakeAssetRepository``/``FakeMarketPriceRepository``, no other test module
needs it — ``test_job_run_repository.py`` exercises the real SQLAlchemy
implementation against a migrated Postgres container instead.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest

from src.domain.ids import generate_uuid7
from src.domain.job_run import JobRun, JobRunStatus
from src.services.job_run import finish_job_run, start_job_run


class _FakeJobRunRepository:
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


def test_start_job_run_creates_running_row() -> None:
    repo = _FakeJobRunRepository()

    row = asyncio.run(start_job_run(repo, job_name="sync_assets", run_date=date(2026, 7, 29)))

    assert row.status == JobRunStatus.RUNNING
    assert len(repo.runs) == 1


def test_finish_job_run_round_trips_to_success() -> None:
    repo = _FakeJobRunRepository()
    started = asyncio.run(start_job_run(repo, job_name="sync_assets", run_date=date(2026, 7, 29)))

    finished = asyncio.run(
        finish_job_run(repo, started.id, status=JobRunStatus.SUCCESS, stats={"synced": 10})
    )

    assert finished.status == JobRunStatus.SUCCESS
    assert finished.stats == {"synced": 10}
    assert finished.finished_at is not None


def test_finish_job_run_rejects_running_status() -> None:
    repo = _FakeJobRunRepository()
    started = asyncio.run(start_job_run(repo, job_name="sync_assets", run_date=date(2026, 7, 29)))

    with pytest.raises(ValueError):
        asyncio.run(finish_job_run(repo, started.id, status=JobRunStatus.RUNNING))
