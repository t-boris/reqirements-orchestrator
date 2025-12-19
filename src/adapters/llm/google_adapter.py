"""
Google Adapter - Implementation of LLM protocol for Gemini models.

Supports Gemini 2.5 Pro, Gemini 1.5 Pro, and other Google models.
"""

import structlog
import google.generativeai as genai

from src.adapters.llm.protocol import LLMProtocol, LLMResponse, Message

logger = structlog.get_logger()


# Model context windows (tokens)
MODEL_CONTEXT_WINDOWS = {
    "gemini-2.5-pro": 1000000,
    "gemini-1.5-pro": 1000000,
    "gemini-1.5-flash": 1000000,
    "gemini-pro": 32000,
}


class GoogleAdapter(LLMProtocol):
    """
    Google Generative AI adapter.

    Provides a unified interface for Google's Gemini models,
    supporting both regular completions and function calling.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-pro",
    ) -> None:
        """
        Initialize Google adapter.

        Args:
            api_key: Google API key.
            model: Model identifier (default: gemini-2.5-pro).
        """
        genai.configure(api_key=api_key)
        self._model_name = model
        self._model = genai.GenerativeModel(model)
        self._context_window = MODEL_CONTEXT_WINDOWS.get(model, 128000)

    @property
    def model_name(self) -> str:
        """Return the model identifier."""
        return self._model_name

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
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        logger.debug(
            "google_complete_request",
            model=self._model_name,
        )

        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        response = await self._model.generate_content_async(
            full_prompt,
            generation_config=generation_config,
        )

        return response.text

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
        # Convert messages to Gemini format
        gemini_messages = []
        system_content = ""

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            elif msg.role == "user":
                content = msg.content
                if system_content and not gemini_messages:
                    content = f"{system_content}\n\n{content}"
                gemini_messages.append({"role": "user", "parts": [content]})
            elif msg.role == "assistant":
                gemini_messages.append({"role": "model", "parts": [msg.content]})

        logger.debug(
            "google_chat_request",
            model=self._model_name,
            message_count=len(gemini_messages),
        )

        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        chat = self._model.start_chat(history=gemini_messages[:-1] if len(gemini_messages) > 1 else [])

        last_message = gemini_messages[-1]["parts"][0] if gemini_messages else ""
        response = await chat.send_message_async(
            last_message,
            generation_config=generation_config,
        )

        content = response.text

        # Estimate token usage (Gemini doesn't always provide this)
        usage = {
            "input_tokens": sum(len(m["parts"][0]) // 4 for m in gemini_messages),
            "output_tokens": len(content) // 4,
        }

        logger.debug(
            "google_chat_response",
            model=self._model_name,
            usage=usage,
        )

        return LLMResponse(
            content=content,
            model=self._model_name,
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
        Generate a response with function calling capability.

        Args:
            messages: List of conversation messages.
            tools: List of tool definitions (OpenAI format, converted internally).
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum response tokens.

        Returns:
            LLMResponse with content or tool calls.
        """
        # Convert OpenAI tool format to Gemini function declarations
        function_declarations = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                function_declarations.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                })

        # Create model with tools
        model_with_tools = genai.GenerativeModel(
            self._model_name,
            tools=function_declarations if function_declarations else None,
        )

        # Convert messages
        gemini_messages = []
        system_content = ""

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            elif msg.role == "user":
                content = msg.content
                if system_content and not gemini_messages:
                    content = f"{system_content}\n\n{content}"
                gemini_messages.append({"role": "user", "parts": [content]})
            elif msg.role == "assistant":
                gemini_messages.append({"role": "model", "parts": [msg.content]})

        logger.debug(
            "google_tools_request",
            model=self._model_name,
            tool_count=len(function_declarations),
        )

        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        chat = model_with_tools.start_chat(history=gemini_messages[:-1] if len(gemini_messages) > 1 else [])

        last_message = gemini_messages[-1]["parts"][0] if gemini_messages else ""
        response = await chat.send_message_async(
            last_message,
            generation_config=generation_config,
        )

        content = response.text
        tool_calls = []

        # Check for function calls in response
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "function_call"):
                    fc = part.function_call
                    tool_calls.append({
                        "id": fc.name,  # Gemini doesn't use IDs
                        "function": {
                            "name": fc.name,
                            "arguments": str(dict(fc.args)),
                        },
                    })

        if tool_calls:
            content = str(tool_calls)

        usage = {
            "input_tokens": sum(len(m["parts"][0]) // 4 for m in gemini_messages),
            "output_tokens": len(content) // 4,
        }

        return LLMResponse(
            content=content,
            model=self._model_name,
            usage=usage,
            raw_response=response,
        )
