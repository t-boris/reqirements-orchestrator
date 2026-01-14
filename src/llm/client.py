"""UnifiedChatClient - Provider-agnostic LLM interface.

This module provides the main interface for business logic to interact with
any LLM provider through a unified API.

Usage:
    from src.llm import get_llm, UnifiedChatClient

    # Quick start - uses project default
    llm = get_llm()
    result = await llm.chat("Hello!")

    # Specify model (provider auto-detected)
    llm = get_llm("gpt-4o")
    result = await llm.invoke(messages)

    # Specify provider explicitly
    llm = get_llm(provider=LLMProvider.ANTHROPIC)
    result = await llm.invoke(messages, tools=[...])
"""

from pydantic import BaseModel

from src.llm.types import (
    LLMProvider,
    LLMConfig,
    LLMResult,
    Message,
    MessageRole,
)
from src.llm.adapters.base import BaseAdapter, ToolDefinition
from src.llm.factory import detect_provider, create_adapter, get_default_model
from src.llm.capabilities import supports_feature
from src.config import get_settings


class UnifiedChatClient:
    """Provider-agnostic LLM client.

    This is the main interface for business logic to use any LLM provider.
    It handles provider detection, adapter creation, and capability validation.

    Examples:
        # Uses default from settings
        client = UnifiedChatClient()

        # Auto-detects OpenAI from model name
        client = UnifiedChatClient(model="gpt-4o")

        # Explicit provider with default model
        client = UnifiedChatClient(provider=LLMProvider.ANTHROPIC)

        # Send messages
        result = await client.invoke(messages)

        # With tools
        result = await client.invoke(messages, tools=[...])

        # With structured output
        result = await client.invoke(messages, response_schema=MyModel)

        # Simple chat (returns text only)
        text = await client.chat("Hello!", system_message="You are helpful.")
    """

    def __init__(
        self,
        model: str | None = None,
        provider: LLMProvider | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout_seconds: float = 30.0,
        api_key: str | None = None,
    ):
        """Initialize the unified chat client.

        Args:
            model: Model name (e.g., "gpt-4o", "claude-3-5-sonnet-latest").
                   If not provided, uses settings default or provider default.
            provider: LLM provider. If not provided, detected from model name.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens in response.
            timeout_seconds: Request timeout.
            api_key: Override API key (otherwise uses settings).
        """
        settings = get_settings()

        # Determine provider and model
        if provider is None and model is None:
            # Use project default
            model = settings.default_llm_model
            provider = detect_provider(model)
        elif provider is None:
            provider = detect_provider(model)
        elif model is None:
            model = get_default_model(provider)

        self.config = LLMConfig(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

        self._adapter: BaseAdapter | None = None

    @property
    def adapter(self) -> BaseAdapter:
        """Lazy-load adapter.

        The adapter is created on first access to avoid initialization
        overhead when creating multiple clients.
        """
        if self._adapter is None:
            self._adapter = create_adapter(self.config)
        return self._adapter

    @property
    def provider(self) -> LLMProvider:
        """Get the current provider."""
        return self.config.provider

    @property
    def model(self) -> str:
        """Get the current model."""
        return self.config.model

    def supports(self, feature: str) -> bool:
        """Check if current provider supports a feature.

        Args:
            feature: Feature name (e.g., "tools", "json_schema", "vision")

        Returns:
            True if the feature is supported
        """
        return supports_feature(self.config.provider, feature)

    async def invoke(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResult:
        """Send messages and get unified result.

        Args:
            messages: List of messages to send
            tools: Optional tool definitions for function calling
            response_schema: Optional Pydantic model for structured output

        Returns:
            Unified LLMResult with text, tool_calls, and metadata

        Raises:
            ValueError: If requesting unsupported feature
        """
        # Validate feature support
        if tools and not self.supports("tools"):
            raise ValueError(f"{self.provider} does not support tool calling")
        if response_schema and not self.supports("json_schema"):
            raise ValueError(f"{self.provider} does not support structured output")

        return await self.adapter.invoke(
            messages=messages,
            tools=tools,
            response_schema=response_schema,
        )

    async def chat(self, user_message: str, system_message: str | None = None) -> str:
        """Simple chat interface - returns text only.

        This is a convenience method for simple conversations without
        tools or structured output.

        Args:
            user_message: The user's message
            system_message: Optional system prompt

        Returns:
            The assistant's text response
        """
        messages = []
        if system_message:
            messages.append(Message(role=MessageRole.SYSTEM, content=system_message))
        messages.append(Message(role=MessageRole.USER, content=user_message))

        result = await self.invoke(messages)
        return result.text


def get_llm(
    model: str | None = None,
    provider: LLMProvider | None = None,
    **kwargs,
) -> UnifiedChatClient:
    """Get an LLM client.

    This is the primary entry point for getting an LLM client. It creates
    a UnifiedChatClient with the specified model/provider.

    Args:
        model: Model name (provider auto-detected if not specified)
        provider: Explicit provider (model defaulted if not specified)
        **kwargs: Additional arguments passed to UnifiedChatClient

    Returns:
        Configured UnifiedChatClient

    Examples:
        # Project default
        llm = get_llm()

        # OpenAI (auto-detected)
        llm = get_llm("gpt-4o")

        # Anthropic with default model
        llm = get_llm(provider=LLMProvider.ANTHROPIC)

        # With custom settings
        llm = get_llm("gpt-4o", temperature=0.0, max_tokens=1000)

        # Use it
        result = await llm.invoke(messages)
        text = await llm.chat("Hello!")
    """
    return UnifiedChatClient(model=model, provider=provider, **kwargs)
