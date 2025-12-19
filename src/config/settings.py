"""
Application settings loaded from environment variables.

Uses pydantic-settings for validation and type coercion.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration.

    All settings are loaded from environment variables.
    See .env.example for documentation of each setting.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # -------------------------------------------------------------------------
    # LLM Configuration
    # -------------------------------------------------------------------------
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    google_api_key: str = Field(default="", description="Google API key")

    llm_provider: Literal["openai", "anthropic", "google"] = Field(
        default="openai",
        description="Active LLM provider",
    )
    llm_model_main: str = Field(
        default="gpt-5-mini",
        description="Main model for agent reasoning",
    )
    llm_model_summarize: str = Field(
        default="gpt-5-nano",
        description="Model for context summarization",
    )

    # -------------------------------------------------------------------------
    # Slack Configuration
    # -------------------------------------------------------------------------
    slack_bot_token: str = Field(default="", description="Slack bot token (xoxb-)")
    slack_signing_secret: str = Field(default="", description="Slack signing secret")
    slack_app_token: str = Field(default="", description="Slack app token (xapp-)")

    # -------------------------------------------------------------------------
    # Jira Configuration
    # -------------------------------------------------------------------------
    jira_url: str = Field(default="", description="Jira instance URL")
    jira_user: str = Field(default="", description="Jira user email")
    jira_api_token: str = Field(default="", description="Jira API token")

    # -------------------------------------------------------------------------
    # Database Configuration
    # -------------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://maro:maro@localhost:5432/maro",
        description="PostgreSQL connection string",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string",
    )

    # -------------------------------------------------------------------------
    # Application Settings
    # -------------------------------------------------------------------------
    graph_save_interval_seconds: int = Field(
        default=30,
        description="Interval for periodic graph persistence",
    )
    context_threshold_percent: int = Field(
        default=80,
        description="Threshold for triggering context summarization",
    )
    polling_interval_ms: int = Field(
        default=5000,
        description="Dashboard polling interval",
    )

    # -------------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------------
    rate_limit_tokens_per_second: float = Field(
        default=10.0,
        description="Leaky bucket tokens per second",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for external APIs",
    )
    retry_backoff_seconds: float = Field(
        default=2.0,
        description="Base backoff time for retries",
    )

    # -------------------------------------------------------------------------
    # Server Configuration
    # -------------------------------------------------------------------------
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Settings: Application settings singleton.
    """
    return Settings()
