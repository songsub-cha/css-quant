"""Job run lifecycle service (SoT C4 — services layer).

``start_job_run``/``finish_job_run`` are a thin wrapper over
``JobRunRepository.start``/``finish`` — their only value over calling the
repository directly is ``finish_job_run``'s rejection of ``RUNNING`` as a
terminal status, the one business rule the repository layer doesn't enforce
(SoT A8 Phase 2's "job_runs" completion bar).

``run_locked_job`` is the actual Arq cron caller (``src.workers.tasks``)
wires through them: acquire the ``JobLock`` for ``(job_name, run_date)``,
``start_job_run``, run ``work()``, ``finish_job_run`` with SUCCESS/FAILED,
always release the lock. A failing ``work()`` is recorded and swallowed
(fail-closed per SoT 원칙 8 — the cron's own ``max_tries=1`` already means a
re-raised exception buys nothing but a noisier log) rather than propagated,
so one bad run never takes the worker process down with it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any
from uuid import UUID

from src.domain.job_run import JobLock, JobRun, JobRunRepository, JobRunStatus

logger = logging.getLogger(__name__)


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


async def run_locked_job(
    job_run_repo: JobRunRepository,
    lock: JobLock,
    *,
    job_name: str,
    run_date: date,
    lock_ttl_seconds: int,
    work: Callable[[], Awaitable[dict[str, Any] | None]],
) -> JobRun | None:
    """Run ``work()`` under a ``(job_name, run_date)`` lock, recording the result in ``job_runs``.

    Returns ``None`` (and creates no ``job_runs`` row) if the lock is
    already held — that means another run is in flight, which is expected
    concurrency to skip, not a failure to record. ``asyncio.CancelledError``
    is not an ``Exception`` subclass, so it propagates through ``work()``
    uncaught and still triggers the ``finally`` release — a cancelled
    worker shutdown must not leave the lock held for its full TTL.
    """
    lock_key = f"job_lock:{job_name}:{run_date.isoformat()}"
    token = await lock.acquire(lock_key, ttl_seconds=lock_ttl_seconds)
    if token is None:
        logger.info("job %s already running for %s — skipping", job_name, run_date)
        return None
    try:
        job_run = await start_job_run(job_run_repo, job_name=job_name, run_date=run_date)
        try:
            stats = await work()
        except Exception as exc:
            logger.error("job %s failed for %s: %s", job_name, run_date, exc)
            return await finish_job_run(
                job_run_repo, job_run.id, status=JobRunStatus.FAILED, error=str(exc)
            )
        return await finish_job_run(
            job_run_repo, job_run.id, status=JobRunStatus.SUCCESS, stats=stats
        )
    finally:
        await lock.release(lock_key, token)
