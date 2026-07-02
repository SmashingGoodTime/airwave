"""Tests for generation job lifecycle helpers."""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.generation_jobs import (
    fail_generation_job,
    finish_generation_job,
    start_generation_job,
)


@pytest.mark.asyncio
async def test_start_generation_job_marks_running(db_session: AsyncSession):
    job = await start_generation_job(
        db_session,
        job_type="generate_track",
        capability="generate_music",
        provider="MockMusicProvider",
        input_data={"prompt": "ambient", "track_id": 1},
        priority=3,
    )
    await db_session.commit()
    await db_session.refresh(job)

    assert job.id is not None
    assert job.status == "running"
    assert job.attempts == 1
    assert job.priority == 3
    assert job.started_at is not None
    assert json.loads(job.input_json)["prompt"] == "ambient"


@pytest.mark.asyncio
async def test_finish_generation_job_marks_succeeded(db_session: AsyncSession):
    job = await start_generation_job(
        db_session,
        job_type="generate_track",
        capability="generate_music",
        provider="MockMusicProvider",
        input_data={"prompt": "ambient"},
    )

    await finish_generation_job(
        db_session,
        job,
        output_data={"track_id": 4, "title": "Done"},
        output_asset_id=9,
    )
    await db_session.commit()
    await db_session.refresh(job)

    assert job.status == "succeeded"
    assert job.output_asset_id == 9
    assert job.finished_at is not None
    assert json.loads(job.output_json)["title"] == "Done"


@pytest.mark.asyncio
async def test_fail_generation_job_marks_failed(db_session: AsyncSession):
    job = await start_generation_job(
        db_session,
        job_type="generate_track",
        capability="generate_music",
        provider="MockMusicProvider",
        input_data={"prompt": "ambient"},
    )

    await fail_generation_job(db_session, job, RuntimeError("provider down"))
    await db_session.commit()
    await db_session.refresh(job)

    assert job.status == "failed"
    assert job.error_message == "provider down"
    assert job.finished_at is not None
