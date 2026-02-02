"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Uses pydantic-settings for validation and .env file support.
    All settings have sensible defaults for local development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database settings
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_user: str = Field(default="maro", description="PostgreSQL user")
    postgres_password: str = Field(default="maro", description="PostgreSQL password")
    postgres_dbname: str = Field(default="maro", description="PostgreSQL database name")

    # Event Store settings
    is_snapshotting_enabled: bool = Field(
        default=True, description="Enable aggregate snapshotting"
    )
    snapshotting_interval: int = Field(
        default=500, description="Snapshot every N events"
    )

    # Slack configuration
    slack_bot_token: str = Field(
        default="", description="Slack bot token (SLACK_BOT_TOKEN env var, xoxb-...)"
    )
    slack_signing_secret: str = Field(
        default="", description="Slack signing secret (SLACK_SIGNING_SECRET env var)"
    )
    slack_app_token: str = Field(
        default="",
        description="Slack app token (SLACK_APP_TOKEN env var, xapp-..., for Socket Mode)",
    )

    # Application settings
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )

    @property
    def postgres_url(self) -> str:
        """Build PostgreSQL connection URL for asyncpg."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_dbname}"
        )

    @property
    def postgres_url_sync(self) -> str:
        """Build PostgreSQL connection URL for psycopg2 (sync operations)."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_dbname}"
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once.
    """
    return Settings()
