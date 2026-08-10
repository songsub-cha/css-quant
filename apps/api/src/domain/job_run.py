"""Batch job execution record schema (SoT C4 ``job_runs`` — domain).

Every batch job (asset/price sync today, future Arq cron jobs) records one
row per execution here — SoT A8 Phase 2's "job_runs + 수집 실패 알림 최소형"
completion bar and the basis for A6.4's "gate failure recorded in
``job_runs.stats``" and D6's "worker detects today's un-run jobs from
``job_runs``" catch-up logic.

``sync_assets``/``sync_prices`` are now wired through ``start``/``finish``
via ``WorkerSettings.cron_jobs`` (``src.workers.tasks``), and ``JobLock``
below is the port the Redis distributed lock preventing concurrent
duplicate ``(job_name, run_date)`` runs implements
(``src.adapters.job_lock.RedisJobLock``). The D6 catch-up query itself
remains a later issue's scope.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base
from src.domain.ids import generate_uuid7


class JobRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobRunRepository(Protocol):
    """Port ``src.services.job_run`` depends on; ``SqlAlchemyJobRunRepository`` implements it."""

    async def start(self, *, job_name: str, run_date: date) -> JobRun:
        """Insert a new ``status=RUNNING`` row; one row per invocation, retries included."""
        ...

    async def finish(
        self,
        job_run_id: UUID,
        *,
        status: JobRunStatus,
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> JobRun:
        """Update the row identified by ``job_run_id`` with a terminal status."""
        ...


class JobLock(Protocol):
    """Port ``src.services.run_locked_job`` depends on; ``RedisJobLock`` implements it.

    Prevents concurrent duplicate ``(job_name, run_date)`` runs (SoT C4) —
    separate from the DB row above because a lock is transient coordination
    state, not an audit record.
    """

    async def acquire(self, key: str, *, ttl_seconds: int) -> str | None:
        """Attempt to acquire the lock; return an opaque token on success, ``None`` if held."""
        ...

    async def release(self, key: str, token: str) -> None:
        """Release the lock only if it is still held by ``token``."""
        ...


class JobRun(Base):
    """Batch job execution row (SoT C4 — ``job_runs``).

    No unique constraint on ``(job_name, run_date)``: this table accumulates
    one row per *execution*, not per ``(job, day)`` — D6's "owner manually
    reruns from the health dashboard" scenario means the same job on the
    same date can have several rows (retries included). Preventing
    *concurrent* duplicate runs of the same ``(job_name, run_date)`` is the
    Redis distributed lock's job (SoT C4), not a DB constraint here.
    """

    __tablename__ = "job_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=generate_uuid7)
    job_name: Mapped[str] = mapped_column(String(100))
    run_date: Mapped[date] = mapped_column(Date)
    status: Mapped[JobRunStatus] = mapped_column(
        SAEnum(JobRunStatus, name="job_run_status", values_callable=lambda e: [x.value for x in e]),
        server_default=JobRunStatus.RUNNING.value,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
