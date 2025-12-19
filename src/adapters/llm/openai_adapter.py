"""
OpenAI Adapter - Implementation of LLM protocol for OpenAI models.

Supports GPT-5, GPT-5 Mini, GPT-5 Nano and other OpenAI models.
"""

import structlog
from openai import AsyncOpenAI

from src.adapters.llm.protocol import LLMProtocol, LLMResponse, Message

logger = structlog.get_logger()


# Model context windows (tokens)
MODEL_CONTEXT_WINDOWS = {
    "gpt-5": 256000,
    "gpt-5-mini": 128000,
    "gpt-5-nano": 64000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
}


class OpenAIAdapter(LLMProtocol):
    """
    OpenAI API adapter.

    Provides a unified interface for OpenAI's chat completion API,
    supporting both regular completions and tool/function calling.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-mini",
        organization: str | None = None,
    ) -> None:
        """
        Initialize OpenAI adapter.

        Args:
            api_key: OpenAI API key.
            model: Model identifier (default: gpt-5-mini).
            organization: Optional organization ID.
        """
        self._client = AsyncOpenAI(
            api_key=api_key,
            organization=organization,
        )
        self._model = model
        self._context_window = MODEL_CONTEXT_WINDOWS.get(model, 128000)

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
        messages: list[Message] = []

        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))

        messages.append(Message(role="user", content=prompt))

        response = await self.chat(
            messages=messages,
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
        openai_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

        logger.debug(
            "openai_chat_request",
            model=self._model,
            message_count=len(messages),
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = {
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }

        logger.debug(
            "openai_chat_response",
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
        Generate a response with function/tool calling capability.

        Args:
            messages: List of conversation messages.
            tools: List of tool definitions (OpenAI function format).
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum response tokens.

        Returns:
            LLMResponse with content or tool calls.
        """
        openai_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

        logger.debug(
            "openai_tools_request",
            model=self._model,
            tool_count=len(tools),
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            tools=tools,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        message = response.choices[0].message
        content = message.content or ""

        # If tool calls present, include them in the response
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
            content = str(tool_calls)  # Serialize for content field

        usage = {
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }

        return LLMResponse(
            content=content,
            model=self._model,
            usage=usage,
            raw_response=response,
        )
