"""
Anthropic Adapter - Implementation of LLM protocol for Claude models.

Supports Claude 3.5 Sonnet, Claude 3 Opus, and other Anthropic models.
"""

import structlog
from anthropic import AsyncAnthropic

from src.adapters.llm.protocol import LLMProtocol, LLMResponse, Message

logger = structlog.get_logger()


# Model context windows (tokens)
MODEL_CONTEXT_WINDOWS = {
    "claude-3-5-sonnet-20241022": 200000,
    "claude-3-opus-20240229": 200000,
    "claude-3-sonnet-20240229": 200000,
    "claude-3-haiku-20240307": 200000,
}


class AnthropicAdapter(LLMProtocol):
    """
    Anthropic API adapter.

    Provides a unified interface for Anthropic's messages API,
    supporting both regular completions and tool use.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
    ) -> None:
        """
        Initialize Anthropic adapter.

        Args:
            api_key: Anthropic API key.
            model: Model identifier (default: claude-3-5-sonnet).
        """
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._context_window = MODEL_CONTEXT_WINDOWS.get(model, 200000)

    @property
    def model_name(self) -> str:
        """Return the model identifier."""
        return self._model

    @property
    def context_window(self) -> int:
        """Return the maximum context window size."""
        return self._context_window

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
        messages = [Message(role="user", content=prompt)]

        response = await self._chat_internal(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.content

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
        # Extract system message if present
        system_prompt = None
        filtered_messages = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                filtered_messages.append(msg)

        return await self._chat_internal(
            messages=filtered_messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _chat_internal(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Internal chat implementation.

        Args:
            messages: List of conversation messages (no system).
            system_prompt: System instructions.
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum response tokens.

        Returns:
            LLMResponse with content and metadata.
        """
        anthropic_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

        logger.debug(
            "anthropic_chat_request",
            model=self._model,
            message_count=len(messages),
        )

        kwargs = {
            "model": self._model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._client.messages.create(**kwargs)

        content = ""
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        logger.debug(
            "anthropic_chat_response",
            model=self._model,
            usage=usage,
        )

        return LLMResponse(
            content=content,
            model=self._model,
            usage=usage,
            raw_response=response,
        )

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Generate a response with tool use capability.

        Args:
            messages: List of conversation messages.
            tools: List of tool definitions (OpenAI format, converted internally).
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum response tokens.

        Returns:
            LLMResponse with content or tool calls.
        """
        # Extract system message
        system_prompt = None
        filtered_messages = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                filtered_messages.append(msg)

        anthropic_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in filtered_messages
        ]

        # Convert OpenAI tool format to Anthropic format
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })

        logger.debug(
            "anthropic_tools_request",
            model=self._model,
            tool_count=len(anthropic_tools),
        )

        kwargs = {
            "model": self._model,
            "messages": anthropic_messages,
            "tools": anthropic_tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._client.messages.create(**kwargs)

        content = ""
        tool_calls = []

        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "function": {
                        "name": block.name,
                        "arguments": str(block.input),
                    },
                })

        if tool_calls:
            content = str(tool_calls)

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        return LLMResponse(
            content=content,
            model=self._model,
            usage=usage,
            raw_response=response,
        )
