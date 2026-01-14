"""Base adapter interface for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from src.llm.types import Message, LLMResult, LLMConfig


class ToolDefinition(BaseModel):
    """Tool definition for function calling."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class BaseAdapter(ABC):
    """Abstract base for LLM provider adapters."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def invoke(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResult:
        """Send messages to LLM and get unified result."""
        pass

    @abstractmethod
    def convert_messages(self, messages: list[Message]) -> Any:
        """Convert canonical messages to provider format."""
        pass

    @abstractmethod
    def parse_response(self, response: Any, latency_ms: float) -> LLMResult:
        """Parse provider response to unified format."""
        pass
