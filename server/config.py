"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings

# Anchor the .env path to the project root so keys load regardless of the
# working directory the app is launched from (e.g. `python -m server.main`
# run from a subdirectory would otherwise find no .env and silently load
# zero API keys).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings read from .env file and environment variables."""

    DATABASE_URL: str = "sqlite+aiosqlite:///./radio.db"
    GOOGLE_API_KEY: str = ""
    # Gemini model id used by the scriptwriter provider. Override in .env
    # if this default is unavailable on your API tier.
    GEMINI_MODEL: str = "gemini-3.6-flash"
    SUNO_API_KEY: str = ""
    SUNO_MODEL: str = "V5_5"
    FISH_AUDIO_API_KEY: str = ""
    # Fish Audio TTS model id. s2.1-pro is the vendor-recommended production
    # model; s2.1-pro-free trades throughput for no per-character billing.
    FISH_AUDIO_MODEL: str = "s2.1-pro"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    AUDIO_DIR: str = "./audio"
    LIQUIDSOAP_HOST: str = "liquidsoap"
    LIQUIDSOAP_PORT: int = 1234
    ICECAST_URL: str = "http://localhost:8080/stream"

    # Comma-separated list of allowed CORS origins for the browser UI. Defaults
    # to common local-dev origins. Set to "*" only if you understand that the
    # write API is unauthenticated (see docs). Empty string disables CORS.
    CORS_ALLOW_ORIGINS: str = (
        "http://localhost:8000,http://127.0.0.1:8000,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    model_config = {"env_file": str(_ENV_FILE), "extra": "ignore"}

    @property
    def cors_origins(self) -> list[str]:
        """Parse ``CORS_ALLOW_ORIGINS`` into a list of origin strings."""
        raw = self.CORS_ALLOW_ORIGINS.strip()
        if not raw:
            return []
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


settings = Settings()
