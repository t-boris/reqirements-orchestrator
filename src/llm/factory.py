"""Factory functions for creating LLM adapters.

This module provides:
- Provider detection from model names
- Adapter instantiation based on provider/model
- Default model lookup for each provider
"""

from src.llm.types import LLMProvider, LLMConfig
from src.llm.adapters.base import BaseAdapter


def detect_provider(model: str) -> LLMProvider:
    """Detect provider from model name.

    Args:
        model: Model name (e.g., "gemini-1.5-pro", "gpt-4o", "claude-3-5-sonnet")

    Returns:
        Detected LLMProvider

    Examples:
        >>> detect_provider("gemini-1.5-flash")
        LLMProvider.GEMINI
        >>> detect_provider("gpt-4o")
        LLMProvider.OPENAI
        >>> detect_provider("claude-3-5-sonnet-latest")
        LLMProvider.ANTHROPIC
    """
    model_lower = model.lower()
    if model_lower.startswith("gemini"):
        return LLMProvider.GEMINI
    elif model_lower.startswith("gpt") or model_lower.startswith("o1"):
        return LLMProvider.OPENAI
    elif model_lower.startswith("claude"):
        return LLMProvider.ANTHROPIC
    else:
        # Default to Gemini (project default)
        return LLMProvider.GEMINI


def create_adapter(config: LLMConfig) -> BaseAdapter:
    """Create adapter instance for the specified provider.

    Args:
        config: LLM configuration with provider, model, and settings

    Returns:
        Initialized adapter for the provider

    Raises:
        ValueError: If provider is unknown
    """
    if config.provider == LLMProvider.GEMINI:
        from src.llm.adapters.gemini import GeminiAdapter
        return GeminiAdapter(config)
    elif config.provider == LLMProvider.OPENAI:
        from src.llm.adapters.openai import OpenAIAdapter
        return OpenAIAdapter(config)
    elif config.provider == LLMProvider.ANTHROPIC:
        from src.llm.adapters.anthropic import AnthropicAdapter
        return AnthropicAdapter(config)
    else:
        raise ValueError(f"Unknown provider: {config.provider}")


def get_default_model(provider: LLMProvider) -> str:
    """Get default model for a provider.

    Args:
        provider: The LLM provider

    Returns:
        Default model name for the provider
    """
    defaults = {
        LLMProvider.GEMINI: "gemini-1.5-flash",
        LLMProvider.OPENAI: "gpt-4o-mini",
        LLMProvider.ANTHROPIC: "claude-3-5-sonnet-latest",
    }
    return defaults.get(provider, "gemini-1.5-flash")
