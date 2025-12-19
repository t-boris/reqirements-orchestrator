"""
LLM Factory - Creates LLM clients based on configuration.

Provides a single entry point for creating LLM adapters,
enabling easy switching between providers.
"""

from typing import Literal

from src.adapters.llm.protocol import LLMProtocol
from src.adapters.llm.openai_adapter import OpenAIAdapter
from src.adapters.llm.anthropic_adapter import AnthropicAdapter
from src.adapters.llm.google_adapter import GoogleAdapter
from src.config.settings import Settings


Provider = Literal["openai", "anthropic", "google"]


def create_llm_client(
    provider: Provider | None = None,
    model: str | None = None,
    settings: Settings | None = None,
) -> LLMProtocol:
    """
    Create an LLM client based on provider configuration.

    Args:
        provider: LLM provider (openai, anthropic, google).
                  If None, uses settings.llm_provider.
        model: Model identifier. If None, uses settings.llm_model_main.
        settings: Application settings. If None, loads from environment.

    Returns:
        Configured LLM client implementing LLMProtocol.

    Raises:
        ValueError: If provider is not supported or API key is missing.
    """
    if settings is None:
        from src.config.settings import get_settings
        settings = get_settings()

    provider = provider or settings.llm_provider
    model = model or settings.llm_model_main

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")
        return OpenAIAdapter(
            api_key=settings.openai_api_key,
            model=model,
        )

    elif provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")
        return AnthropicAdapter(
            api_key=settings.anthropic_api_key,
            model=model,
        )

    elif provider == "google":
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for Google provider")
        return GoogleAdapter(
            api_key=settings.google_api_key,
            model=model,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def create_summarization_client(settings: Settings | None = None) -> LLMProtocol:
    """
    Create an LLM client specifically for summarization tasks.

    Uses a smaller/cheaper model optimized for summarization.

    Args:
        settings: Application settings. If None, loads from environment.

    Returns:
        Configured LLM client for summarization.
    """
    if settings is None:
        from src.config.settings import get_settings
        settings = get_settings()

    return create_llm_client(
        provider=settings.llm_provider,
        model=settings.llm_model_summarize,
        settings=settings,
    )
