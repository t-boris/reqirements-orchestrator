"""
LLM Protocol - Abstract interface for language model providers.

Defines a common interface that all LLM adapters must implement,
enabling seamless switching between providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """
    Standardized response from any LLM provider.

    Attributes:
        content: The generated text response.
        model: Model identifier used.
        usage: Token usage statistics.
        raw_response: Original provider response for debugging.
    """

    content: str
    model: str
    usage: dict[str, int]  # {"input_tokens": N, "output_tokens": M}
    raw_response: Any = None


@dataclass
class Message:
    """A single message in a conversation."""

    role: str  # "system", "user", "assistant"
    content: str


class LLMProtocol(ABC):
    """
    Abstract protocol for LLM providers.

    All LLM adapters (OpenAI, Anthropic, Google) implement this interface,
    allowing the core domain to remain provider-agnostic.
    """

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Generate a completion for a single prompt.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum response tokens.

        Returns:
            Generated text response.
        """
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Generate a response for a conversation.

        Args:
            messages: List of conversation messages.
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum response tokens.

        Returns:
            LLMResponse with content and metadata.
        """
        ...

    @abstractmethod
    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Generate a response with function/tool calling capability.

        Args:
            messages: List of conversation messages.
            tools: List of tool definitions (OpenAI function format).
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum response tokens.

        Returns:
            LLMResponse with content or tool calls.
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
        ...

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Return the maximum context window size in tokens."""
        ...
