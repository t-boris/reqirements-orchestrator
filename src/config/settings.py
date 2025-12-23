"""
Application Settings - Pydantic-based configuration management.

Loads settings from environment variables with validation and type coercion.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # LLM Providers
    # -------------------------------------------------------------------------
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    google_api_key: str = Field(default="", description="Google AI API key")
    default_llm_model: str = Field(default="gpt-4o", description="Default LLM model")

    # -------------------------------------------------------------------------
    # Slack
    # -------------------------------------------------------------------------
    slack_bot_token: str = Field(default="", description="Slack bot token (xoxb-)")
    slack_app_token: str = Field(default="", description="Slack app token (xapp-)")
    slack_signing_secret: str = Field(default="", description="Slack signing secret")

    # -------------------------------------------------------------------------
    # Jira (for MCP server)
    # -------------------------------------------------------------------------
    jira_url: str = Field(default="", description="Jira instance URL")
    # Basic auth (legacy)
    jira_user: str = Field(default="", description="Jira user email (basic auth)")
    jira_api_token: str = Field(default="", description="Jira API token (basic auth)")
    # OAuth2 auth
    jira_client_id: str = Field(default="", description="Jira OAuth2 client ID")
    jira_client_secret: str = Field(default="", description="Jira OAuth2 client secret")
    # Default project
    jira_default_project: str = Field(default="", description="Default Jira project key")
    jira_mcp_url: str = Field(default="http://localhost:3000/sse", description="Jira MCP server URL")

    # -------------------------------------------------------------------------
    # Zep Memory
    # -------------------------------------------------------------------------
    zep_api_url: str = Field(default="http://localhost:8001", description="Zep API URL")

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://maro:maro@localhost:5432/maro",
        description="PostgreSQL connection URL",
    )

    # -------------------------------------------------------------------------
    # LangSmith Observability
    # -------------------------------------------------------------------------
    langchain_tracing_v2: bool = Field(default=True, description="Enable LangSmith tracing")
    langchain_api_key: str = Field(default="", description="LangSmith API key")
    langchain_project: str = Field(default="maro-v2", description="LangSmith project name")
    langchain_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        description="LangSmith endpoint",
    )

    # -------------------------------------------------------------------------
    # Application Settings
    # -------------------------------------------------------------------------
    confidence_threshold_main: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for main bot to respond",
    )
    confidence_threshold_persona: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for persona bots (architect, PM, security)",
    )
    max_reflexion_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum draft-critique cycles",
    )

    # -------------------------------------------------------------------------
    # Server
    # -------------------------------------------------------------------------
    environment: str = Field(default="development", description="Environment (development/production)")
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Singleton Settings instance.
    """
    return Settings()
