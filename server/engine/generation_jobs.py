"""Helpers for durable AI generation job lifecycle tracking."""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.models.generation_job import GenerationJob


async def start_generation_job(
    session: AsyncSession,
    *,
    job_type: str,
    capability: str | None,
    provider: str | None,
    input_data: dict[str, Any] | None = None,
    priority: int = 0,
) -> GenerationJob:
    """Create a running generation job row."""
    job = GenerationJob(
        job_type=job_type,
        capability=capability,
        provider=provider,
        status="running",
        priority=priority,
        attempts=1,
        input_json=_to_json(input_data),
        started_at=_now(),
    )
    session.add(job)
    await session.flush()
    return job


async def finish_generation_job(
    session: AsyncSession,
    job: GenerationJob,
    *,
    output_data: dict[str, Any] | None = None,
    output_asset_id: int | None = None,
) -> GenerationJob:
    """Mark a generation job as succeeded."""
    job.status = "succeeded"
    job.output_json = _to_json(output_data)
    job.output_asset_id = output_asset_id
    job.finished_at = _now()
    await session.flush()
    return job


async def fail_generation_job(
    session: AsyncSession,
    job: GenerationJob,
    error: Exception | str,
) -> GenerationJob:
    """Mark a generation job as failed."""
    job.status = "failed"
    job.error_message = str(error)
    job.finished_at = _now()
    await session.flush()
    return job


def _to_json(data: dict[str, Any] | None) -> str | None:
    """Serialize optional structured data for storage."""
    if data is None:
        return None
    return json.dumps(data, default=str)


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)
