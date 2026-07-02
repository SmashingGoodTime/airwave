"""Setup wizard API endpoints for initial station configuration."""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.dj_config import DJConfig
from server.models.station import Station
from server.models.style import Style
from server.utils.env import update_env_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])


class StyleInput(BaseModel):
    """Schema for a style provided during setup."""

    name: str
    prompt: str
    weight: float = 1.0


class SetupCompleteRequest(BaseModel):
    """Schema for the setup completion request body."""

    station_name: str = "AI Radio"
    timezone: str = "UTC"
    dj_name: str = "DJ Claude"
    personality_prompt: Optional[str] = None
    voice_id: Optional[str] = None
    content_policy: str = "clean_vocals"
    google_api_key: Optional[str] = None
    suno_api_key: Optional[str] = None
    fish_audio_api_key: Optional[str] = None
    styles: list[StyleInput] = []


@router.get("/status")
async def get_setup_status(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Check whether initial station setup has been completed.

    Args:
        session: Async database session.

    Returns:
        A dict with setup_complete boolean.
    """
    result = await session.execute(select(Station).limit(1))
    station = result.scalar_one_or_none()
    if station is None:
        return {"setup_complete": False}
    return {"setup_complete": station.setup_complete}


@router.post("/complete")
async def complete_setup(
    body: SetupCompleteRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Complete initial station setup by creating Station and DJConfig records.

    Args:
        body: Setup configuration including station name, DJ settings,
              API keys, and initial styles.
        session: Async database session.

    Returns:
        A dict with success boolean.

    Raises:
        HTTPException: 409 if setup has already been completed.
    """
    # Update the existing singleton Station row (seeded by init_db) rather
    # than inserting a second one that no reader would ever see.
    result = await session.execute(select(Station).order_by(Station.id).limit(1))
    station = result.scalar_one_or_none()
    if station is None:
        station = Station()
        session.add(station)

    if station.setup_complete:
        raise HTTPException(
            status_code=409, detail="Setup has already been completed."
        )

    station.timezone = body.timezone
    station.setup_complete = True

    # Update the existing default DJConfig if present, else create one.
    result = await session.execute(
        select(DJConfig).order_by(DJConfig.id).limit(1)
    )
    dj_config = result.scalar_one_or_none()
    if dj_config is None:
        dj_config = DJConfig(is_default=True)
        session.add(dj_config)
    dj_config.station_name = body.station_name
    dj_config.dj_name = body.dj_name
    dj_config.personality_prompt = body.personality_prompt
    dj_config.voice_id = body.voice_id
    dj_config.content_policy = body.content_policy

    for style_input in body.styles:
        # Skip blank rows the wizard may submit alongside valid ones.
        if not style_input.name.strip() or not style_input.prompt.strip():
            continue
        style = Style(
            name=style_input.name.strip(),
            prompt=style_input.prompt.strip(),
            weight=style_input.weight,
        )
        session.add(style)

    await session.commit()

    # Persist API keys to .env and reinitialize providers
    env_keys: dict[str, str] = {}
    if body.google_api_key:
        env_keys["GOOGLE_API_KEY"] = body.google_api_key
    if body.suno_api_key:
        env_keys["SUNO_API_KEY"] = body.suno_api_key
    if body.fish_audio_api_key:
        env_keys["FISH_AUDIO_API_KEY"] = body.fish_audio_api_key

    if env_keys:
        update_env_file(env_keys)

        # Update the current process environment so Settings picks up the
        # new values (Docker-injected env vars would otherwise take
        # precedence over the .env file).
        for var_name, value in env_keys.items():
            os.environ[var_name] = value

        # Reload settings from the updated environment and reinitialize providers
        from server.config import Settings
        from server.providers.registry import ProviderRegistry

        refreshed_settings = Settings()
        registry = ProviderRegistry.get_instance()
        await registry.initialize(refreshed_settings)
        logger.info("Providers reinitialized after setup with new API keys")

    return {"success": True}
