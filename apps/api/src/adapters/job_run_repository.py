"""SQLAlchemy implementation of the job run repository port (SoT C4 — adapters).

Implements ``src.domain.job_run.JobRunRepository`` structurally, importing only
``domain`` per the layer contract ("adapters는 domain만 import") — same
structure as ``SqlAlchemyMarketPriceRepository``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.job_run import JobRun, JobRunStatus


class SqlAlchemyJobRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(self, *, job_name: str, run_date: date) -> JobRun:
        row = JobRun(job_name=job_name, run_date=run_date, status=JobRunStatus.RUNNING)
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def finish(
        self,
        job_run_id: UUID,
        *,
        status: JobRunStatus,
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> JobRun:
        result = await self._session.execute(select(JobRun).where(JobRun.id == job_run_id))
        row = result.scalar_one()
        row.status = status
        row.finished_at = datetime.now(UTC)
        row.error = error
        row.stats = stats
        await self._session.commit()
        await self._session.refresh(row)
        return row
