"""
Channel Config Store - PostgreSQL storage for channel configuration.

Provides persistent storage for per-channel settings including:
- Jira configuration
- LLM model selection
- Bot personality settings
- Persona knowledge overrides
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any

import structlog

from src.graph.checkpointer import get_pool

logger = structlog.get_logger()


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PersonalityConfig:
    """Bot personality settings (0.0-1.0 scale)."""
    humor: float = 0.2
    formality: float = 0.6
    emoji_usage: float = 0.2
    verbosity: float = 0.5


@dataclass
class ChannelConfig:
    """Complete channel configuration."""
    channel_id: str

    # Jira settings
    jira_project_key: str | None = None
    jira_default_issue_type: str = "Story"

    # LLM settings
    default_model: str = "gemini-2.5-pro"

    # Bot personality
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)

    # Persona knowledge overrides
    # Format: {"architect": {"inline": "...", "files": ["file1.md"]}, ...}
    persona_knowledge: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "channel_id": self.channel_id,
            "jira_project_key": self.jira_project_key,
            "jira_default_issue_type": self.jira_default_issue_type,
            "default_model": self.default_model,
            "personality": asdict(self.personality),
            "persona_knowledge": self.persona_knowledge,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChannelConfig":
        """Create from dictionary."""
        personality_data = data.get("personality", {})
        return cls(
            channel_id=data["channel_id"],
            jira_project_key=data.get("jira_project_key"),
            jira_default_issue_type=data.get("jira_default_issue_type", "Story"),
            default_model=data.get("default_model", "gpt-5.2"),
            personality=PersonalityConfig(
                humor=personality_data.get("humor", 0.2),
                formality=personality_data.get("formality", 0.6),
                emoji_usage=personality_data.get("emoji_usage", 0.2),
                verbosity=personality_data.get("verbosity", 0.5),
            ),
            persona_knowledge=data.get("persona_knowledge", {}),
        )


# =============================================================================
# SQL Schema
# =============================================================================

CREATE_CHANNEL_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS channel_config (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL UNIQUE,

    -- Jira settings
    jira_project_key TEXT,
    jira_default_issue_type TEXT DEFAULT 'Story',

    -- LLM settings
    default_model TEXT DEFAULT 'gpt-5.2',

    -- Bot personality (0.0-1.0 scale)
    personality_humor FLOAT DEFAULT 0.2,
    personality_formality FLOAT DEFAULT 0.6,
    personality_emoji FLOAT DEFAULT 0.2,
    personality_verbosity FLOAT DEFAULT 0.5,

    -- Persona knowledge overrides (JSONB)
    persona_knowledge JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_channel_config_channel_id
ON channel_config(channel_id);
"""


# =============================================================================
# Database Operations
# =============================================================================


async def init_channel_config_store() -> None:
    """
    Initialize the channel config store tables.

    Should be called during application startup.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(CREATE_CHANNEL_CONFIG_TABLE)
        logger.info("channel_config_store_initialized")


async def get_channel_config(channel_id: str) -> ChannelConfig:
    """
    Get channel configuration.

    Args:
        channel_id: Slack channel ID.

    Returns:
        ChannelConfig with stored values or defaults.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                channel_id,
                jira_project_key,
                jira_default_issue_type,
                default_model,
                personality_humor,
                personality_formality,
                personality_emoji,
                personality_verbosity,
                persona_knowledge
            FROM channel_config
            WHERE channel_id = $1
            """,
            channel_id,
        )

        if row:
            # Parse persona_knowledge - asyncpg may return JSONB as string
            persona_knowledge = row["persona_knowledge"]
            if isinstance(persona_knowledge, str):
                persona_knowledge = json.loads(persona_knowledge) if persona_knowledge else {}
            elif persona_knowledge is None:
                persona_knowledge = {}

            return ChannelConfig(
                channel_id=row["channel_id"],
                jira_project_key=row["jira_project_key"],
                jira_default_issue_type=row["jira_default_issue_type"] or "Story",
                default_model=row["default_model"] or "gpt-5.2",
                personality=PersonalityConfig(
                    humor=row["personality_humor"] or 0.2,
                    formality=row["personality_formality"] or 0.6,
                    emoji_usage=row["personality_emoji"] or 0.2,
                    verbosity=row["personality_verbosity"] or 0.5,
                ),
                persona_knowledge=persona_knowledge,
            )

        # Return default config if not found
        return ChannelConfig(channel_id=channel_id)


async def save_channel_config(config: ChannelConfig) -> None:
    """
    Save channel configuration (upsert).

    Args:
        config: ChannelConfig to save.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO channel_config (
                channel_id,
                jira_project_key,
                jira_default_issue_type,
                default_model,
                personality_humor,
                personality_formality,
                personality_emoji,
                personality_verbosity,
                persona_knowledge,
                updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (channel_id) DO UPDATE SET
                jira_project_key = $2,
                jira_default_issue_type = $3,
                default_model = $4,
                personality_humor = $5,
                personality_formality = $6,
                personality_emoji = $7,
                personality_verbosity = $8,
                persona_knowledge = $9,
                updated_at = NOW()
            """,
            config.channel_id,
            config.jira_project_key,
            config.jira_default_issue_type,
            config.default_model,
            config.personality.humor,
            config.personality.formality,
            config.personality.emoji_usage,
            config.personality.verbosity,
            json.dumps(config.persona_knowledge),
        )

        logger.info(
            "channel_config_saved",
            channel_id=config.channel_id,
            model=config.default_model,
        )


async def delete_channel_config(channel_id: str) -> bool:
    """
    Delete channel configuration.

    Args:
        channel_id: Slack channel ID.

    Returns:
        True if deleted, False if not found.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM channel_config
            WHERE channel_id = $1
            """,
            channel_id,
        )

        deleted = result.endswith("1")

        if deleted:
            logger.info("channel_config_deleted", channel_id=channel_id)

        return deleted


# =============================================================================
# Available Models (December 2025)
# =============================================================================

AVAILABLE_MODELS = [
    # OpenAI (December 2025)
    {"value": "gpt-5.2", "label": "GPT-5.2 (OpenAI Flagship)", "provider": "openai"},
    {"value": "gpt-5", "label": "GPT-5 (OpenAI)", "provider": "openai"},
    {"value": "gpt-5-mini", "label": "GPT-5 Mini (OpenAI)", "provider": "openai"},
    {"value": "o3", "label": "o3 (OpenAI Reasoning)", "provider": "openai"},
    {"value": "o4-mini", "label": "o4 Mini (OpenAI)", "provider": "openai"},
    {"value": "gpt-4.1", "label": "GPT-4.1 (OpenAI)", "provider": "openai"},

    # Anthropic (December 2025)
    {"value": "claude-opus-4-5", "label": "Claude Opus 4.5 (Anthropic)", "provider": "anthropic"},
    {"value": "claude-sonnet-4-5-20250929", "label": "Claude Sonnet 4.5 (Anthropic)", "provider": "anthropic"},
    {"value": "claude-haiku-4-5", "label": "Claude Haiku 4.5 (Anthropic)", "provider": "anthropic"},
    {"value": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4 (Anthropic)", "provider": "anthropic"},

    # Google Gemini (December 2025)
    {"value": "gemini-3-pro", "label": "Gemini 3 Pro Preview (Google)", "provider": "google"},
    {"value": "gemini-3-flash", "label": "Gemini 3 Flash Preview (Google)", "provider": "google"},
    {"value": "gemini-2.5-pro", "label": "Gemini 2.5 Pro (Google)", "provider": "google"},
    {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash (Google)", "provider": "google"},
    {"value": "gemini-2.0-flash", "label": "Gemini 2.0 Flash (Google)", "provider": "google"},
]


def get_available_models() -> list[dict[str, str]]:
    """Get list of available LLM models for selection."""
    return AVAILABLE_MODELS


def get_model_provider(model_name: str) -> str:
    """Get the provider for a given model name."""
    for model in AVAILABLE_MODELS:
        if model["value"] == model_name:
            return model["provider"]
    # Default to openai for unknown models
    return "openai"
