"""Environment-driven application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with safe local-development defaults."""

    database_url: str = "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow"
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    gemini_timeout_seconds: float | None = None

    model_config = SettingsConfigDict(
        env_prefix="OPSFLOW_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Load and cache application settings."""

    return Settings()
