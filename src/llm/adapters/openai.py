"""OpenAI provider adapter using langchain-openai."""

import logging
import time
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from src.config import get_settings
from src.llm.adapters.base import BaseAdapter, ToolDefinition
from src.llm.types import (
    FinishReason,
    LLMConfig,
    LLMProvider,
    LLMResult,
    Message,
    MessageRole,
    TokenUsage,
    ToolCall,
)

logger = logging.getLogger(__name__)


class OpenAIAdapter(BaseAdapter):
    """OpenAI provider adapter using langchain-openai."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        settings = get_settings()
        api_key = config.api_key or settings.openai_api_key
        if not api_key:
            raise ValueError("OpenAI API key required")

        self.client = ChatOpenAI(
            model=config.model,
            api_key=api_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout_seconds,
        )

    def convert_messages(self, messages: list[Message]) -> list[BaseMessage]:
        """Convert canonical messages to LangChain format."""
        result = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                result.append(SystemMessage(content=msg.content))
            elif msg.role == MessageRole.USER:
                result.append(HumanMessage(content=msg.content))
            elif msg.role == MessageRole.ASSISTANT:
                result.append(AIMessage(content=msg.content))
            elif msg.role == MessageRole.TOOL:
                result.append(
                    ToolMessage(
                        content=msg.content,
                        tool_call_id=msg.tool_call_id or "",
                        name=msg.name or "",
                    )
                )
        return result

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        """Convert tool definitions to OpenAI format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    def parse_response(self, response: Any, latency_ms: float) -> LLMResult:
        """Parse LangChain response to unified format."""
        text = response.content if hasattr(response, "content") else ""

        tool_calls = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("name", ""),
                        arguments=tc.get("args", {}),
                    )
                )

        finish_reason = FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP

        usage = TokenUsage()
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = TokenUsage(
                prompt_tokens=um.get("input_tokens", 0),
                completion_tokens=um.get("output_tokens", 0),
                total_tokens=um.get("total_tokens", 0),
            )

        return LLMResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            provider=LLMProvider.OPENAI,
            model=self.config.model,
            latency_ms=latency_ms,
            usage=usage,
            raw=response,
        )

    async def invoke(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResult:
        """Send messages to OpenAI and get unified result."""
        start_time = time.perf_counter()

        try:
            lc_messages = self.convert_messages(messages)

            client = self.client
            if tools:
                client = client.bind_tools(self._convert_tools(tools))

            if response_schema:
                client = client.with_structured_output(response_schema)

            response = await client.ainvoke(lc_messages)

            latency_ms = (time.perf_counter() - start_time) * 1000

            result = self.parse_response(response, latency_ms)

            logger.info(
                "OpenAI request completed",
                extra={
                    "request_id": result.request_id,
                    "provider": result.provider.value,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                },
            )

            return result

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"OpenAI request failed: {e}")
            return LLMResult(
                text="",
                finish_reason=FinishReason.ERROR,
                provider=LLMProvider.OPENAI,
                model=self.config.model,
                latency_ms=latency_ms,
            )
