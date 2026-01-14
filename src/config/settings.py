"""Settings configuration using pydantic-settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore extra env vars
    )

    # Environment
    environment: str = "development"
    debug: bool = False

    # Database
    database_url: str = "postgresql://localhost:5432/jira_analyst"

    # Slack
    slack_bot_token: str
    slack_app_token: str  # For Socket Mode
    slack_signing_secret: Optional[str] = None

    # Jira
    jira_url: str
    jira_user: str
    jira_api_token: str
    jira_default_project: Optional[str] = None

    # LLM
    google_api_key: str  # For Gemini
    default_llm_model: str = "gemini-1.5-flash"

    # Logging
    log_level: str = "INFO"


# Singleton pattern for settings access
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the application settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
