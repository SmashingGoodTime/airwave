"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings read from .env file and environment variables."""

    DATABASE_URL: str = "sqlite+aiosqlite:///./radio.db"
    GOOGLE_API_KEY: str = ""
    SUNO_API_KEY: str = ""
    SUNO_MODEL: str = "V5_5"
    FISH_AUDIO_API_KEY: str = ""
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    AUDIO_DIR: str = "./audio"
    LIQUIDSOAP_HOST: str = "liquidsoap"
    LIQUIDSOAP_PORT: int = 1234
    LIQUIDSOAP_HARBOR_PORT: int = 8005
    ICECAST_URL: str = "http://localhost:8080/stream"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
