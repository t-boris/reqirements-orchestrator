"""Multi-provider LLM abstraction layer.

This package provides a unified interface for interacting with multiple LLM providers
(Gemini, OpenAI, Anthropic) with consistent types, capability detection, and
standardized result formats.

Usage:
    from src.llm import LLMProvider, Message, LLMResult, get_capabilities

    # Check provider capabilities
    caps = get_capabilities(LLMProvider.GEMINI)
    if caps.tools:
        # Provider supports tool calling
        ...
"""

# Enums
from src.llm.types import (
    LLMProvider,
    MessageRole,
    FinishReason,
)

# Core types
from src.llm.types import (
    Message,
    ToolCall,
    TokenUsage,
    LLMResult,
    LLMConfig,
)

# Capabilities
from src.llm.capabilities import (
    ProviderCapabilities,
    CAPABILITIES,
    get_capabilities,
    supports_feature,
)

__all__ = [
    # Enums
    "LLMProvider",
    "MessageRole",
    "FinishReason",
    # Core types
    "Message",
    "ToolCall",
    "TokenUsage",
    "LLMResult",
    "LLMConfig",
    # Capabilities
    "ProviderCapabilities",
    "CAPABILITIES",
    "get_capabilities",
    "supports_feature",
]
