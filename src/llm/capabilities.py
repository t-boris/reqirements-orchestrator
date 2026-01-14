"""Capability matrix for feature detection across LLM providers."""

from dataclasses import dataclass
from src.llm.types import LLMProvider


@dataclass(frozen=True)
class ProviderCapabilities:
    """What a provider can do."""
    tools: bool = False  # Function/tool calling
    json_schema: bool = False  # Structured output with schema
    vision: bool = False  # Image input
    streaming: bool = False  # Stream responses
    system_message: bool = True  # Supports system role

    # Quirks
    max_tools: int = 128  # Max tools in single request
    parallel_tool_calls: bool = True  # Can call multiple tools at once


# Capability matrix by provider
CAPABILITIES: dict[LLMProvider, ProviderCapabilities] = {
    LLMProvider.GEMINI: ProviderCapabilities(
        tools=True,
        json_schema=True,
        vision=True,
        streaming=True,
        system_message=True,
        max_tools=128,
        parallel_tool_calls=True,
    ),
    LLMProvider.OPENAI: ProviderCapabilities(
        tools=True,
        json_schema=True,
        vision=True,
        streaming=True,
        system_message=True,
        max_tools=128,
        parallel_tool_calls=True,
    ),
    LLMProvider.ANTHROPIC: ProviderCapabilities(
        tools=True,
        json_schema=True,
        vision=True,
        streaming=True,
        system_message=True,
        max_tools=128,
        parallel_tool_calls=True,
    ),
}


def get_capabilities(provider: LLMProvider) -> ProviderCapabilities:
    """Get capabilities for a provider."""
    return CAPABILITIES.get(provider, ProviderCapabilities())


def supports_feature(provider: LLMProvider, feature: str) -> bool:
    """Check if provider supports a specific feature."""
    caps = get_capabilities(provider)
    return getattr(caps, feature, False)
