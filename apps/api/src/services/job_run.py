"""Job run lifecycle service (SoT C4 — services layer).

Thin wrapper over ``JobRunRepository.start``/``finish`` — this module's only
value over calling the repository directly is ``finish_job_run``'s rejection
of ``RUNNING`` as a terminal status, the one business rule the repository
layer doesn't enforce (SoT A8 Phase 2's "job_runs" completion bar). Wiring an
actual caller (Arq cron jobs, ``sync_assets``/``sync_prices``) through these
two functions is later issues' scope.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from src.domain.job_run import JobRun, JobRunRepository, JobRunStatus


async def start_job_run(job_run_repo: JobRunRepository, *, job_name: str, run_date: date) -> JobRun:
    return await job_run_repo.start(job_name=job_name, run_date=run_date)


async def finish_job_run(
    job_run_repo: JobRunRepository,
    job_run_id: UUID,
    *,
    status: JobRunStatus,
    error: str | None = None,
    stats: dict[str, Any] | None = None,
) -> JobRun:
    if status is JobRunStatus.RUNNING:
        raise ValueError("finish_job_run requires a terminal status, got RUNNING")
    return await job_run_repo.finish(job_run_id, status=status, error=error, stats=stats)
