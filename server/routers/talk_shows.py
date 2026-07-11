"""Talk show configuration and topic management API endpoints."""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_serializer, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.talk_segment import TalkSegment
from server.models.talk_show_config import TalkShowConfig
from server.models.talk_topic import TalkTopic
from server.utils.timeutils import to_utc_iso

router = APIRouter(prefix="/api/talk", tags=["talk_shows"])


# --- Pydantic Schemas ---


class TalkConfigCreate(BaseModel):
    """Schema for creating a talk show configuration."""

    name: str = Field(min_length=1)
    host_voice_id: Optional[str] = None
    host_voice_settings: Optional[str] = None
    host_personality_prompt: Optional[str] = None
    cohost_voices: Optional[str] = None
    segment_min_duration: int = Field(default=120, ge=1, le=7200)
    segment_max_duration: int = Field(default=600, ge=1, le=7200)
    segment_gap: int = Field(default=5, ge=0, le=100)
    topic_rotation: Literal["weighted", "sequential", "random"] = "weighted"
    max_speakers: int = Field(default=3, ge=1, le=8)
    allow_call_ins: bool = False
    intro_style: Optional[str] = None
    outro_style: Optional[str] = None
    conversation_style: Optional[str] = None

    @model_validator(mode="after")
    def validate_duration_range(self) -> "TalkConfigCreate":
        """Ensure the segment duration range is ordered."""
        if self.segment_min_duration > self.segment_max_duration:
            raise ValueError("segment_min_duration must be less than or equal to segment_max_duration")
        return self


class TalkConfigUpdate(BaseModel):
    """Schema for updating a talk show configuration."""

    name: Optional[str] = Field(default=None, min_length=1)
    host_voice_id: Optional[str] = None
    host_voice_settings: Optional[str] = None
    host_personality_prompt: Optional[str] = None
    cohost_voices: Optional[str] = None
    segment_min_duration: Optional[int] = Field(default=None, ge=1, le=7200)
    segment_max_duration: Optional[int] = Field(default=None, ge=1, le=7200)
    segment_gap: Optional[int] = Field(default=None, ge=0, le=100)
    topic_rotation: Optional[Literal["weighted", "sequential", "random"]] = None
    max_speakers: Optional[int] = Field(default=None, ge=1, le=8)
    allow_call_ins: Optional[bool] = None
    intro_style: Optional[str] = None
    outro_style: Optional[str] = None
    conversation_style: Optional[str] = None

    @model_validator(mode="after")
    def validate_duration_range(self) -> "TalkConfigUpdate":
        """Ensure the segment duration range is ordered when both values are provided."""
        if (
            self.segment_min_duration is not None
            and self.segment_max_duration is not None
            and self.segment_min_duration > self.segment_max_duration
        ):
            raise ValueError("segment_min_duration must be less than or equal to segment_max_duration")
        return self


class TalkConfigResponse(BaseModel):
    """Schema for talk config responses."""

    id: int
    name: str
    host_voice_id: Optional[str] = None
    host_voice_settings: Optional[str] = None
    host_personality_prompt: Optional[str] = None
    cohost_voices: Optional[str] = None
    segment_min_duration: int
    segment_max_duration: int
    segment_gap: int
    topic_rotation: str
    max_speakers: int
    allow_call_ins: bool
    intro_style: Optional[str] = None
    outro_style: Optional[str] = None
    conversation_style: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


class TopicCreate(BaseModel):
    """Schema for creating a talk topic."""

    talk_config_id: int
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    topic_type: Literal["monologue", "conversation", "debate", "interview"] = "conversation"
    active: bool = True
    weight: float = Field(default=1.0, gt=0)
    max_plays: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class TopicUpdate(BaseModel):
    """Schema for updating a talk topic."""

    title: Optional[str] = Field(default=None, min_length=1)
    prompt: Optional[str] = Field(default=None, min_length=1)
    topic_type: Optional[Literal["monologue", "conversation", "debate", "interview"]] = None
    active: Optional[bool] = None
    weight: Optional[float] = Field(default=None, gt=0)
    max_plays: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class TopicResponse(BaseModel):
    """Schema for topic responses."""

    id: int
    talk_config_id: int
    title: str
    prompt: str
    topic_type: str
    active: bool
    weight: float
    play_count: int
    max_plays: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


class SegmentResponse(BaseModel):
    """Schema for talk segment responses."""

    id: int
    show_id: Optional[int] = None
    talk_config_id: Optional[int] = None
    topic_id: Optional[int] = None
    segment_type: str
    script_text: Optional[str] = None
    duration: Optional[float] = None
    speakers: Optional[str] = None
    status: str
    created_at: datetime
    played_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "played_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


class PreviewRequest(BaseModel):
    """Schema for generating a talk segment preview."""

    config_id: int
    topic_id: Optional[int] = None


# --- Talk Config Endpoints ---


@router.get("/configs", response_model=list[TalkConfigResponse])
async def list_talk_configs(
    session: AsyncSession = Depends(get_session),
) -> list[TalkShowConfig]:
    """List all talk show configurations.

    Args:
        session: Async database session.

    Returns:
        List of all talk configs.
    """
    result = await session.execute(select(TalkShowConfig))
    return list(result.scalars().all())


@router.post("/configs", response_model=TalkConfigResponse, status_code=201)
async def create_talk_config(
    body: TalkConfigCreate,
    session: AsyncSession = Depends(get_session),
) -> TalkShowConfig:
    """Create a new talk show configuration.

    Args:
        body: Talk config creation data.
        session: Async database session.

    Returns:
        The newly created talk config.
    """
    config = TalkShowConfig(**body.model_dump())
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


@router.put("/configs/{config_id}", response_model=TalkConfigResponse)
async def update_talk_config(
    config_id: int,
    body: TalkConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> TalkShowConfig:
    """Update an existing talk show configuration.

    Args:
        config_id: ID of the config to update.
        body: Fields to update.
        session: Async database session.

    Returns:
        The updated talk config.
    """
    result = await session.execute(
        select(TalkShowConfig).where(TalkShowConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="Talk config not found")

    update_data = body.model_dump(exclude_unset=True)
    segment_min_duration = update_data.get(
        "segment_min_duration", config.segment_min_duration
    )
    segment_max_duration = update_data.get(
        "segment_max_duration", config.segment_max_duration
    )
    if segment_min_duration > segment_max_duration:
        raise HTTPException(
            status_code=422,
            detail="segment_min_duration must be less than or equal to segment_max_duration",
        )

    for key, value in update_data.items():
        setattr(config, key, value)

    await session.commit()
    await session.refresh(config)
    return config


@router.delete("/configs/{config_id}")
async def delete_talk_config(
    config_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a talk show configuration.

    Args:
        config_id: ID of the config to delete.
        session: Async database session.

    Returns:
        Confirmation dict.
    """
    result = await session.execute(
        select(TalkShowConfig).where(TalkShowConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="Talk config not found")

    await session.delete(config)
    await session.commit()
    return {"success": True}


# --- Topic Endpoints ---


@router.get("/configs/{config_id}/topics", response_model=list[TopicResponse])
async def list_topics(
    config_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[TalkTopic]:
    """List all topics for a talk show configuration.

    Args:
        config_id: ID of the talk config.
        session: Async database session.

    Returns:
        List of topics for the config.
    """
    result = await session.execute(
        select(TalkTopic)
        .where(TalkTopic.talk_config_id == config_id)
        .order_by(TalkTopic.weight.desc())
    )
    return list(result.scalars().all())


@router.post("/topics", response_model=TopicResponse, status_code=201)
async def create_topic(
    body: TopicCreate,
    session: AsyncSession = Depends(get_session),
) -> TalkTopic:
    """Create a new talk topic.

    Args:
        body: Topic creation data.
        session: Async database session.

    Returns:
        The newly created topic.
    """
    topic = TalkTopic(**body.model_dump())
    session.add(topic)
    await session.commit()
    await session.refresh(topic)
    return topic


@router.put("/topics/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: int,
    body: TopicUpdate,
    session: AsyncSession = Depends(get_session),
) -> TalkTopic:
    """Update an existing talk topic.

    Args:
        topic_id: ID of the topic to update.
        body: Fields to update.
        session: Async database session.

    Returns:
        The updated topic.
    """
    result = await session.execute(
        select(TalkTopic).where(TalkTopic.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(topic, key, value)

    await session.commit()
    await session.refresh(topic)
    return topic


@router.delete("/topics/{topic_id}")
async def delete_topic(
    topic_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a talk topic.

    Args:
        topic_id: ID of the topic to delete.
        session: Async database session.

    Returns:
        Confirmation dict.
    """
    result = await session.execute(
        select(TalkTopic).where(TalkTopic.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    await session.delete(topic)
    await session.commit()
    return {"success": True}


# --- Segment Endpoints ---


@router.get("/segments", response_model=list[SegmentResponse])
async def list_segments(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[TalkSegment]:
    """List recent talk segments.

    Args:
        limit: Maximum number of segments to return.
        session: Async database session.

    Returns:
        List of recent talk segments.
    """
    result = await session.execute(
        select(TalkSegment)
        .order_by(TalkSegment.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.post("/preview")
async def preview_talk_segment(
    body: PreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Generate a preview talk segment without queueing it.

    Args:
        body: Preview request containing the talk config and optional topic.
        session: Async database session.

    Returns:
        The generated segment data.
    """
    from server.engine.talk_show import TalkShowEngine
    from server.models.show import Show

    result = await session.execute(
        select(TalkShowConfig).where(TalkShowConfig.id == body.config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="Talk config not found")

    # Create a temporary show for the preview
    temp_show = Show(
        name="Preview",
        show_type="talk",
        talk_config_id=body.config_id,
    )

    engine = TalkShowEngine()
    segment = await engine.generate_segment(
        session, temp_show, config, topic_id=body.topic_id, preview=True
    )

    if segment is None:
        raise HTTPException(status_code=500, detail="Failed to generate preview segment")

    return {
        "segment_id": segment.id,
        "segment_type": segment.segment_type,
        "script_text": segment.script_text,
        "duration": segment.duration,
        "speakers": segment.speakers,
        "has_audio": segment.audio_filepath is not None,
    }
