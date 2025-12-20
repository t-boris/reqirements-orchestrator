"""
Slack Channel Configuration - Maps channels to Jira projects.

Manages per-channel settings including Jira project mapping,
AI model configuration, personality parameters, and custom prompts.
"""

from dataclasses import dataclass, field
from typing import Any


# Available LLM models by provider (December 2025)
LLM_MODELS = {
    "openai": [
        ("gpt-5.2-pro", "GPT-5.2 Pro - Most accurate"),
        ("gpt-5.2-thinking", "GPT-5.2 Thinking - Best for coding"),
        ("gpt-5.2-instant", "GPT-5.2 Instant - Fast"),
        ("gpt-5.2-codex", "GPT-5.2 Codex - Agentic coding"),
        ("gpt-5", "GPT-5 - Flagship"),
        ("gpt-5-mini", "GPT-5 Mini - Cost-efficient"),
        ("o4-mini", "o4-mini - Fast reasoning"),
    ],
    "anthropic": [
        ("claude-opus-4.5", "Claude Opus 4.5 - Most intelligent"),
        ("claude-sonnet-4.5", "Claude Sonnet 4.5 - Best for agents"),
        ("claude-haiku-4.5", "Claude Haiku 4.5 - Fast, low-latency"),
        ("claude-opus-4.1", "Claude Opus 4.1 - Agentic tasks"),
        ("claude-3.7-sonnet", "Claude 3.7 Sonnet - Hybrid reasoning"),
    ],
    "google": [
        ("gemini-3-pro", "Gemini 3 Pro - PhD-level reasoning"),
        ("gemini-3-flash", "Gemini 3 Flash - Fast and cheap"),
        ("gemini-3-deep-think", "Gemini 3 Deep Think - Enhanced reasoning"),
        ("gemini-2.5-pro", "Gemini 2.5 Pro - Best price-performance"),
        ("gemini-2.5-flash", "Gemini 2.5 Flash - High volume"),
    ],
}

# Default personality parameter values
DEFAULT_TEMPERATURE = 70
DEFAULT_HUMOR = 30
DEFAULT_VERBOSITY = 50
DEFAULT_FORMALITY = 60
DEFAULT_TECHNICAL_DEPTH = 70
DEFAULT_EMOJI_USAGE = 20


@dataclass
class ChannelSettings:
    """Settings for a single Slack channel."""

    channel_id: str
    jira_project_key: str = ""
    jira_project_id: str = ""
    enabled: bool = True

    # AI Model Settings
    llm_provider: str = ""  # openai/anthropic/google (empty = use default)
    llm_model: str = ""  # Empty = use default from Settings

    # Personality Parameters (0-100)
    temperature: int = DEFAULT_TEMPERATURE
    humor: int = DEFAULT_HUMOR
    verbosity: int = DEFAULT_VERBOSITY
    formality: int = DEFAULT_FORMALITY
    technical_depth: int = DEFAULT_TECHNICAL_DEPTH
    emoji_usage: int = DEFAULT_EMOJI_USAGE

    # Custom prompts (empty = use defaults)
    prompt_product_manager: str = ""
    prompt_architect: str = ""
    prompt_graph_admin: str = ""

    custom_settings: dict[str, Any] = field(default_factory=dict)

    def get_personality_modifier(self) -> str:
        """Generate personality modifier text for system prompts."""
        humor_desc = "playful and witty" if self.humor > 70 else "professional with occasional light humor" if self.humor > 30 else "strictly professional"
        verbosity_desc = "detailed and thorough" if self.verbosity > 70 else "balanced" if self.verbosity > 30 else "concise and to-the-point"
        formality_desc = "formal and professional" if self.formality > 70 else "semi-formal" if self.formality > 30 else "casual and friendly"
        tech_desc = "expert-level technical" if self.technical_depth > 70 else "intermediate" if self.technical_depth > 30 else "beginner-friendly"
        emoji_desc = "use emojis frequently" if self.emoji_usage > 70 else "use emojis occasionally" if self.emoji_usage > 30 else "avoid emojis"

        return f"""
## Personality Settings
- Communication style: {formality_desc}
- Humor: {humor_desc}
- Detail level: {verbosity_desc}
- Technical depth: {tech_desc}
- Emojis: {emoji_desc}
"""


class ChannelConfig:
    """
    Manages channel-specific configuration.

    Maps Slack channels to Jira projects and stores
    per-channel settings.
    """

    def __init__(self) -> None:
        """Initialize empty channel config."""
        self._channels: dict[str, ChannelSettings] = {}

    def get_channel(self, channel_id: str) -> ChannelSettings | None:
        """
        Get settings for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Channel settings or None if not configured.
        """
        return self._channels.get(channel_id)

    def set_channel(
        self,
        channel_id: str,
        jira_project_key: str = "",
        jira_project_id: str = "",
        llm_provider: str = "",
        llm_model: str = "",
        temperature: int = DEFAULT_TEMPERATURE,
        humor: int = DEFAULT_HUMOR,
        verbosity: int = DEFAULT_VERBOSITY,
        formality: int = DEFAULT_FORMALITY,
        technical_depth: int = DEFAULT_TECHNICAL_DEPTH,
        emoji_usage: int = DEFAULT_EMOJI_USAGE,
        prompt_product_manager: str = "",
        prompt_architect: str = "",
        prompt_graph_admin: str = "",
        **custom_settings: Any,
    ) -> ChannelSettings:
        """
        Configure a channel.

        Args:
            channel_id: Slack channel ID.
            jira_project_key: Jira project key (e.g., "PROJ").
            jira_project_id: Jira project ID.
            llm_provider: LLM provider (openai/anthropic/google).
            llm_model: LLM model name.
            temperature: Creativity (0-100).
            humor: Playfulness (0-100).
            verbosity: Detail level (0-100).
            formality: Tone formality (0-100).
            technical_depth: Technical depth (0-100).
            emoji_usage: Emoji frequency (0-100).
            prompt_product_manager: Custom PM prompt.
            prompt_architect: Custom Architect prompt.
            prompt_graph_admin: Custom Graph Admin prompt.
            **custom_settings: Additional settings.

        Returns:
            Updated channel settings.
        """
        settings = ChannelSettings(
            channel_id=channel_id,
            jira_project_key=jira_project_key,
            jira_project_id=jira_project_id,
            llm_provider=llm_provider,
            llm_model=llm_model,
            temperature=temperature,
            humor=humor,
            verbosity=verbosity,
            formality=formality,
            technical_depth=technical_depth,
            emoji_usage=emoji_usage,
            prompt_product_manager=prompt_product_manager,
            prompt_architect=prompt_architect,
            prompt_graph_admin=prompt_graph_admin,
            custom_settings=custom_settings,
        )
        self._channels[channel_id] = settings
        return settings

    def update_channel(self, channel_id: str, **updates: Any) -> ChannelSettings:
        """
        Update specific fields of a channel's settings.

        Args:
            channel_id: Slack channel ID.
            **updates: Fields to update.

        Returns:
            Updated channel settings.
        """
        settings = self.get_channel(channel_id)
        if not settings:
            settings = ChannelSettings(channel_id=channel_id)

        for key, value in updates.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

        self._channels[channel_id] = settings
        return settings

    def get_jira_project(self, channel_id: str) -> str | None:
        """
        Get Jira project key for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Jira project key or None.
        """
        settings = self.get_channel(channel_id)
        return settings.jira_project_key if settings else None

    def is_enabled(self, channel_id: str) -> bool:
        """
        Check if MARO is enabled for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            True if enabled (default True for unconfigured channels).
        """
        settings = self.get_channel(channel_id)
        return settings.enabled if settings else True

    def disable_channel(self, channel_id: str) -> None:
        """Disable MARO for a channel."""
        if channel_id in self._channels:
            self._channels[channel_id].enabled = False
        else:
            self._channels[channel_id] = ChannelSettings(
                channel_id=channel_id,
                enabled=False,
            )

    def enable_channel(self, channel_id: str) -> None:
        """Enable MARO for a channel."""
        if channel_id in self._channels:
            self._channels[channel_id].enabled = True

    def list_channels(self) -> list[ChannelSettings]:
        """Get all configured channels."""
        return list(self._channels.values())

    def to_dict(self) -> dict:
        """Serialize configuration."""
        return {
            channel_id: {
                "channel_id": settings.channel_id,
                "jira_project_key": settings.jira_project_key,
                "jira_project_id": settings.jira_project_id,
                "enabled": settings.enabled,
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
                "temperature": settings.temperature,
                "humor": settings.humor,
                "verbosity": settings.verbosity,
                "formality": settings.formality,
                "technical_depth": settings.technical_depth,
                "emoji_usage": settings.emoji_usage,
                "prompt_product_manager": settings.prompt_product_manager,
                "prompt_architect": settings.prompt_architect,
                "prompt_graph_admin": settings.prompt_graph_admin,
                "custom_settings": settings.custom_settings,
            }
            for channel_id, settings in self._channels.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelConfig":
        """Deserialize configuration."""
        config = cls()
        for channel_id, settings_data in data.items():
            config._channels[channel_id] = ChannelSettings(
                channel_id=settings_data["channel_id"],
                jira_project_key=settings_data.get("jira_project_key", ""),
                jira_project_id=settings_data.get("jira_project_id", ""),
                enabled=settings_data.get("enabled", True),
                llm_provider=settings_data.get("llm_provider", ""),
                llm_model=settings_data.get("llm_model", ""),
                temperature=settings_data.get("temperature", DEFAULT_TEMPERATURE),
                humor=settings_data.get("humor", DEFAULT_HUMOR),
                verbosity=settings_data.get("verbosity", DEFAULT_VERBOSITY),
                formality=settings_data.get("formality", DEFAULT_FORMALITY),
                technical_depth=settings_data.get("technical_depth", DEFAULT_TECHNICAL_DEPTH),
                emoji_usage=settings_data.get("emoji_usage", DEFAULT_EMOJI_USAGE),
                prompt_product_manager=settings_data.get("prompt_product_manager", ""),
                prompt_architect=settings_data.get("prompt_architect", ""),
                prompt_graph_admin=settings_data.get("prompt_graph_admin", ""),
                custom_settings=settings_data.get("custom_settings", {}),
            )
        return config
