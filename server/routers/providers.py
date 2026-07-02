"""Provider settings API endpoints for managing Google API key configuration."""

import logging
import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from server.utils.env import update_env_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])

PROVIDER_KEY_ENV = {
    "music": "SUNO_API_KEY",
    "scriptwriter": "GOOGLE_API_KEY",
    "voice": "FISH_AUDIO_API_KEY",
}


def _mask_key(value: str) -> str:
    """Mask an API key for safe display.

    Args:
        value: The raw API key string.

    Returns:
        A masked version showing first 4 and last 4 characters,
        or '****' for short keys, or '' if empty.
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _get_key(env_var: str) -> str:
    """Read an API key from os.environ first, then fall back to Settings.

    Args:
        env_var: Environment variable name (e.g. "GOOGLE_API_KEY").

    Returns:
        The key value, or "" if not configured.
    """
    value = os.environ.get(env_var, "")
    if value:
        return value
    from server.config import Settings

    s = Settings()
    return getattr(s, env_var, "")


class ProviderKeyInfo(BaseModel):
    """Masked representation of a single API key."""

    env_var: str
    label: str
    masked_value: str
    is_configured: bool


class ProviderStatusResponse(BaseModel):
    """Full provider settings state."""

    keys: list[ProviderKeyInfo]
    health: dict


class ProviderUpdateRequest(BaseModel):
    """Payload for updating API keys."""

    google_api_key: Optional[str] = None
    suno_api_key: Optional[str] = None
    fish_audio_api_key: Optional[str] = None


class ProviderTestRequest(BaseModel):
    """Optional payload for testing an unsaved candidate API key."""

    api_key: Optional[str] = None


class ProviderTestResult(BaseModel):
    """Result of testing a single provider's connection."""

    provider: str
    healthy: bool
    status: str
    tested_candidate: bool = False
    error: Optional[str] = None


@router.get("", response_model=ProviderStatusResponse)
async def get_provider_settings() -> ProviderStatusResponse:
    """Get current provider configuration with masked keys and health status.

    Returns:
        Provider status including masked API keys and health.
    """
    from server.providers.registry import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    raw_google = _get_key("GOOGLE_API_KEY")
    raw_suno = _get_key("SUNO_API_KEY")
    raw_fish = _get_key("FISH_AUDIO_API_KEY")

    keys = [
        ProviderKeyInfo(
            env_var="GOOGLE_API_KEY",
            label="Google AI — Scripts Generator",
            masked_value=_mask_key(raw_google),
            is_configured=bool(raw_google),
        ),
        ProviderKeyInfo(
            env_var="SUNO_API_KEY",
            label="Suno — Music Generator",
            masked_value=_mask_key(raw_suno),
            is_configured=bool(raw_suno),
        ),
        ProviderKeyInfo(
            env_var="FISH_AUDIO_API_KEY",
            label="Fish Audio — DJ Voice Synthesis",
            masked_value=_mask_key(raw_fish),
            is_configured=bool(raw_fish),
        ),
    ]

    try:
        health = await registry.check_all_health()
    except Exception as exc:
        logger.warning("Health check failed during provider settings GET: %s", exc)
        health = {}

    return ProviderStatusResponse(
        keys=keys,
        health=health,
    )


@router.put("", response_model=ProviderStatusResponse)
async def update_provider_settings(
    body: ProviderUpdateRequest,
) -> ProviderStatusResponse:
    """Update API keys, write to .env, and reinitialize providers.

    Args:
        body: The provider update request with optional API keys.

    Returns:
        Updated provider status (same as GET).
    """
    env_keys: dict[str, str] = {}

    if body.google_api_key is not None:
        env_keys["GOOGLE_API_KEY"] = body.google_api_key
    if body.suno_api_key is not None:
        env_keys["SUNO_API_KEY"] = body.suno_api_key
    if body.fish_audio_api_key is not None:
        env_keys["FISH_AUDIO_API_KEY"] = body.fish_audio_api_key

    if env_keys:
        update_env_file(env_keys)

        # Update process environment
        for var_name, value in env_keys.items():
            if value:
                os.environ[var_name] = value
            else:
                os.environ.pop(var_name, None)

        # Reload settings and reinitialize providers
        from server.config import Settings
        from server.providers.registry import ProviderRegistry

        refreshed_settings = Settings()
        registry = ProviderRegistry.get_instance()
        await registry.initialize(refreshed_settings)
        logger.info("Providers reinitialized after settings update")

    return await get_provider_settings()


@router.post("/test/{provider_name}", response_model=ProviderTestResult)
async def test_provider(
    provider_name: str,
    body: Optional[ProviderTestRequest] = None,
) -> ProviderTestResult:
    """Test a single provider's health/connectivity.

    Args:
        provider_name: One of 'music', 'scriptwriter', or 'voice'.
        body: Optional candidate key payload. Candidate keys are tested
              without being persisted.

    Returns:
        Test result with health status and optional error message.
    """
    from server.config import Settings
    from server.providers.registry import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    candidate_key = (body.api_key or "").strip() if body else ""

    if candidate_key:
        env_var = PROVIDER_KEY_ENV.get(provider_name)
        if env_var is None:
            return ProviderTestResult(
                provider=provider_name,
                healthy=False,
                status="unknown_provider",
                tested_candidate=True,
                error=f"Unknown provider type: {provider_name}",
            )

        candidate_config = Settings().model_copy(update={env_var: candidate_key})
        result = await registry.check_capability_health(provider_name, candidate_config)
        return ProviderTestResult(
            provider=result["provider"] or provider_name,
            healthy=result["healthy"],
            status=result["status"],
            tested_candidate=True,
            error=result["error"],
        )

    getter_map = {
        "music": registry.get_music_provider,
        "scriptwriter": registry.get_scriptwriter_provider,
        "voice": registry.get_voice_provider,
    }

    getter = getter_map.get(provider_name)
    if getter is None:
        return ProviderTestResult(
            provider=provider_name,
            healthy=False,
            status="unknown_provider",
            tested_candidate=False,
            error=f"Unknown provider type: {provider_name}",
        )

    provider = getter()
    if provider is None:
        return ProviderTestResult(
            provider=provider_name,
            healthy=False,
            status="unconfigured",
            tested_candidate=False,
            error="Not configured",
        )

    try:
        healthy = await provider.check_status()
        return ProviderTestResult(
            provider=provider_name,
            healthy=healthy,
            status="healthy" if healthy else "unhealthy",
            tested_candidate=False,
            error=None if healthy else "Provider reported unhealthy",
        )
    except Exception as exc:
        logger.warning("Provider test failed for %s: %s", provider_name, exc)
        return ProviderTestResult(
            provider=provider_name,
            healthy=False,
            status="error",
            tested_candidate=False,
            error=str(exc),
        )
