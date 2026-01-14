"""Multi-provider LLM abstraction layer.

This package provides a unified interface for interacting with multiple LLM providers
(Gemini, OpenAI, Anthropic) with consistent types, capability detection, and
standardized result formats.

Usage:
    from src.llm import get_llm, UnifiedChatClient, Message

    # Quick start - uses project default
    llm = get_llm()
    result = await llm.chat("Hello!")

    # Specify model (provider auto-detected)
    llm = get_llm("gpt-4o")
    result = await llm.invoke(messages)

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

# Client and Factory
from src.llm.client import (
    UnifiedChatClient,
    get_llm,
)
from src.llm.factory import (
    detect_provider,
    create_adapter,
    get_default_model,
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
    # Client
    "UnifiedChatClient",
    "get_llm",
    # Factory
    "detect_provider",
    "create_adapter",
    "get_default_model",
]
