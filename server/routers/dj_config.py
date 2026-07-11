"""DJ configuration API endpoints."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.dj_config import DJConfig
from server.models.station import get_station
from server.providers.registry import ProviderRegistry
from server.utils.timeutils import resolve_timezone, to_utc_iso, utcnow_naive
from server.utils.voice import parse_voice_settings

router = APIRouter(prefix="/api/dj", tags=["dj"])


class DJConfigResponse(BaseModel):
    """Schema for DJ config responses."""

    id: Optional[int] = None
    name: str = "Default"
    is_default: bool = False
    station_name: str = "AI Radio"
    dj_name: str = "DJ Claude"
    personality_prompt: Optional[str] = None
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
    voice_settings: Optional[str] = None
    break_frequency: int = 3
    break_frequency_variance: int = 1
    mention_time: bool = True
    mention_weather: bool = False
    content_policy: str = "clean_vocals"
    content_policy_suffix: Optional[str] = None
    max_break_duration: int = 60
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_serializer("updated_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


class DJConfigCreate(BaseModel):
    """Schema for creating a new DJ configuration."""

    name: str = "Default"
    station_name: str = "AI Radio"
    dj_name: str = "DJ Claude"
    personality_prompt: Optional[str] = None
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
    voice_settings: Optional[str] = None
    break_frequency: int = Field(default=3, ge=1, le=20)
    break_frequency_variance: int = Field(default=1, ge=0, le=20)
    mention_time: bool = True
    mention_weather: bool = False
    content_policy: Literal["instrumental_only", "clean_vocals", "no_restrictions"] = "clean_vocals"
    content_policy_suffix: Optional[str] = None
    max_break_duration: int = Field(default=60, ge=1, le=600)


class DJConfigUpdate(BaseModel):
    """Schema for updating DJ configuration."""

    name: Optional[str] = None
    station_name: Optional[str] = None
    dj_name: Optional[str] = None
    personality_prompt: Optional[str] = None
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
    voice_settings: Optional[str] = None
    break_frequency: Optional[int] = Field(default=None, ge=1, le=20)
    break_frequency_variance: Optional[int] = Field(default=None, ge=0, le=20)
    mention_time: Optional[bool] = None
    mention_weather: Optional[bool] = None
    content_policy: Optional[Literal["instrumental_only", "clean_vocals", "no_restrictions"]] = None
    content_policy_suffix: Optional[str] = None
    max_break_duration: Optional[int] = Field(default=None, ge=1, le=600)


class DJPreviewRequest(BaseModel):
    """Schema for requesting a DJ break or voice preview."""

    voice_id: Optional[str] = None
    voice_provider: Optional[str] = None


async def _load_default_config(session: AsyncSession) -> Optional[DJConfig]:
    """Load the default DJ configuration, falling back to the oldest config.

    Args:
        session: Async database session.

    Returns:
        The default (or first-created) DJ config, or None if none exists.
    """
    result = await session.execute(
        select(DJConfig)
        .where(DJConfig.is_default.is_(True))
        .order_by(DJConfig.id)
        .limit(1)
    )
    config = result.scalar_one_or_none()
    if config is None:
        result = await session.execute(
            select(DJConfig).order_by(DJConfig.id).limit(1)
        )
        config = result.scalar_one_or_none()
    return config


@router.get("/config", response_model=DJConfigResponse)
async def get_dj_config(
    session: AsyncSession = Depends(get_session),
) -> DJConfigResponse:
    """Get the active DJ configuration.

    Args:
        session: Async database session.

    Returns:
        The current DJ config or defaults if none exists.
    """
    config = await _load_default_config(session)
    if config is None:
        return DJConfigResponse()
    return DJConfigResponse.model_validate(config)


@router.put("/config", response_model=DJConfigResponse)
async def update_dj_config(
    body: DJConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> DJConfigResponse:
    """Update or create the default DJ configuration.

    Args:
        body: Fields to update.
        session: Async database session.

    Returns:
        The updated DJ config.
    """
    config = await _load_default_config(session)

    if config is None:
        config = DJConfig(is_default=True)
        session.add(config)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    config.updated_at = utcnow_naive()

    await session.commit()
    await session.refresh(config)

    # Switch active voice provider only after the change is durably saved,
    # so a failed commit cannot leave the registry out of sync with the DB.
    if "voice_provider" in update_data and update_data["voice_provider"]:
        registry = ProviderRegistry.get_instance()
        registry.set_active_voice_provider(update_data["voice_provider"])

    return DJConfigResponse.model_validate(config)


## --- Multi-config CRUD ---


@router.get("/configs", response_model=list[DJConfigResponse])
async def list_dj_configs(
    session: AsyncSession = Depends(get_session),
) -> list[DJConfig]:
    """List all DJ configurations.

    Args:
        session: Async database session.

    Returns:
        List of all DJ configs, default first.
    """
    result = await session.execute(
        select(DJConfig).order_by(DJConfig.is_default.desc(), DJConfig.id)
    )
    return list(result.scalars().all())


@router.post("/configs", response_model=DJConfigResponse, status_code=201)
async def create_dj_config(
    body: DJConfigCreate,
    session: AsyncSession = Depends(get_session),
) -> DJConfig:
    """Create a new DJ configuration.

    Args:
        body: DJ config creation data.
        session: Async database session.

    Returns:
        The newly created DJ config.
    """
    config = DJConfig(**body.model_dump())
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


@router.get("/configs/{config_id}", response_model=DJConfigResponse)
async def get_dj_config_by_id(
    config_id: int,
    session: AsyncSession = Depends(get_session),
) -> DJConfig:
    """Get a specific DJ configuration by ID.

    Args:
        config_id: ID of the config.
        session: Async database session.

    Returns:
        The DJ config.
    """
    result = await session.execute(
        select(DJConfig).where(DJConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="DJ config not found")
    return config


@router.put("/configs/{config_id}", response_model=DJConfigResponse)
async def update_dj_config_by_id(
    config_id: int,
    body: DJConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> DJConfig:
    """Update a specific DJ configuration.

    Args:
        config_id: ID of the config to update.
        body: Fields to update.
        session: Async database session.

    Returns:
        The updated DJ config.
    """
    result = await session.execute(
        select(DJConfig).where(DJConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="DJ config not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    config.updated_at = utcnow_naive()

    await session.commit()
    await session.refresh(config)

    # Registry switch happens only after a successful commit (see PUT /config).
    if "voice_provider" in update_data and update_data["voice_provider"]:
        registry = ProviderRegistry.get_instance()
        registry.set_active_voice_provider(update_data["voice_provider"])

    return config


@router.delete("/configs/{config_id}")
async def delete_dj_config(
    config_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a DJ configuration.

    Cannot delete the default config or one linked to a show.

    Args:
        config_id: ID of the config to delete.
        session: Async database session.

    Returns:
        Confirmation dict.
    """
    from server.models.show import Show

    result = await session.execute(
        select(DJConfig).where(DJConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="DJ config not found")
    if config.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default DJ config")

    # Check if any show references this config
    show_result = await session.execute(
        select(Show).where(Show.dj_config_id == config_id).limit(1)
    )
    if show_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a DJ config that is linked to a show",
        )

    await session.delete(config)
    await session.commit()
    return {"success": True}


@router.post("/configs/{config_id}/set-default", response_model=DJConfigResponse)
async def set_default_dj_config(
    config_id: int,
    session: AsyncSession = Depends(get_session),
) -> DJConfig:
    """Mark a DJ configuration as the station default.

    Clears ``is_default`` on all other configs.

    Args:
        config_id: ID of the config to set as default.
        session: Async database session.

    Returns:
        The updated DJ config.
    """
    result = await session.execute(
        select(DJConfig).where(DJConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="DJ config not found")

    # Clear default on all others
    all_result = await session.execute(select(DJConfig))
    for c in all_result.scalars().all():
        c.is_default = c.id == config_id

    await session.commit()
    await session.refresh(config)
    return config


@router.post("/preview")
async def preview_dj_break(
    body: Optional[DJPreviewRequest] = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Generate a preview DJ break script or test a specific voice.

    Args:
        body: Optional request body specifying voice_id to preview.
        session: Async database session.

    Returns:
        A dict with the generated script text and optional audio URL.
    """
    registry = ProviderRegistry.get_instance()

    # Determine voice provider
    voice_provider_key = body.voice_provider if body else None
    if voice_provider_key:
        voice = registry.get_voice_provider_by_key(voice_provider_key)
    else:
        voice = registry.get_voice_provider()

    # If previewing a specific voice_id, do a quick test rendering
    if body and body.voice_id:
        if voice is None:
            return {"script": None, "audio_url": None, "error": "No voice provider configured"}

        script_text = "Hello! This is a preview of my voice on AI Radio. I hope you like how I sound!"
        try:
            voice_settings = {"voice_id": body.voice_id}
            audio_path = await voice.render(script_text, voice_settings)
            audio_url = f"/audio/breaks/{Path(audio_path).name}"
            return {"script": script_text, "audio_url": audio_url}
        except Exception as exc:
            return {"script": None, "audio_url": None, "error": str(exc)}

    # Otherwise, generate a full DJ break script using Gemini
    scriptwriter = registry.get_scriptwriter_provider()
    if scriptwriter is None:
        return {"script": None, "audio_url": None, "error": "No scriptwriter provider configured"}

    # Load DJ config for context (same default-first resolution as GET /config)
    config = await _load_default_config(session)

    # Convert to station timezone
    station = await get_station(session)
    station_tz = resolve_timezone(station.timezone if station else None)
    local_now = datetime.now(timezone.utc).astimezone(station_tz)

    context = {
        "station_name": config.station_name if config else "AI Radio",
        "dj_name": config.dj_name if config else "DJ",
        "personality_prompt": config.personality_prompt if config else "",
        "max_duration": config.max_break_duration if config else 60,
        "mention_time": config.mention_time if config else True,
        "recent_tracks": [],
        "announcements": [],
        "current_time": local_now.strftime("%I:%M %p"),
    }

    try:
        script_result = await scriptwriter.write_break(context)
        script_text = script_result.get("script_text", "")

        # Optionally render audio if voice provider is available
        audio_url = None
        if voice and config and config.voice_id:
            voice_settings = parse_voice_settings(
                config.voice_settings, config.voice_id
            )
            audio_path = await voice.render(script_text, voice_settings)
            audio_url = f"/audio/breaks/{Path(audio_path).name}"

        return {"script": script_text, "audio_url": audio_url}

    except Exception as exc:
        return {"script": None, "audio_url": None, "error": str(exc)}


@router.get("/voice-providers")
async def list_voice_providers() -> list:
    """List available voice providers.

    Returns:
        A list of dicts with provider key, display name, and active flag.
    """
    registry = ProviderRegistry.get_instance()
    return registry.list_voice_providers()


@router.get("/voices")
async def list_voices(provider: Optional[str] = None) -> list:
    """List available TTS voices from a voice provider.

    Args:
        provider: Optional provider key. If omitted, uses the active provider.

    Returns:
        A list of available voices, or empty list if no provider configured.
    """
    registry = ProviderRegistry.get_instance()

    if provider:
        voice = registry.get_voice_provider_by_key(provider)
    else:
        voice = registry.get_voice_provider()

    if voice is None:
        return []

    try:
        return await voice.list_voices()
    except Exception:
        return []
