"""Core type definitions for the multi-provider LLM abstraction layer."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class MessageRole(str, Enum):
    """Canonical message roles."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """Canonical message format."""
    role: MessageRole
    content: str
    name: Optional[str] = None  # For tool messages
    tool_call_id: Optional[str] = None  # For tool responses


class ToolCall(BaseModel):
    """Normalized tool call from LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


class FinishReason(str, Enum):
    """Why the LLM stopped generating."""
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class TokenUsage(BaseModel):
    """Token usage tracking."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResult(BaseModel):
    """Unified result from any provider."""
    # Content
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason = FinishReason.STOP

    # Metadata
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider: LLMProvider
    model: str

    # Observability
    latency_ms: float = 0
    usage: TokenUsage = Field(default_factory=TokenUsage)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Raw response for debugging
    raw: Optional[Any] = None


class LLMConfig(BaseModel):
    """Configuration for LLM client."""
    provider: LLMProvider
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: float = 30.0
    api_key: Optional[str] = None  # Override from settings
