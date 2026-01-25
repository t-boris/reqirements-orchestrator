"""Context specification for goal-driven context building."""
from typing import Optional
from pydantic import BaseModel, Field

from src.schemas.intent import SuperMode


class ContextSpec(BaseModel):
    """Specification for what context to load.

    Context is built from goal, not from "what's available."
    """

    mode: SuperMode
    """Current super mode (BUILD, OPERATE, DECIDE, THINK, CHAT)."""

    target: str
    """Target identifier: 'channel_id:thread_ts' or 'workitem_id'."""

    purpose: str
    """What the context is for: 'extract draft fields', 'explain decision'."""

    budget_tokens: int = Field(default=4000, ge=500, le=16000)
    """Maximum tokens for context. Enforced during building."""

    required_artifacts: list[str] = Field(default_factory=list)
    """Artifacts that must be loaded: ['review_artifact', 'decisions']."""

    include_history: bool = True
    """Whether to load conversation history."""

    history_limit: int = Field(default=20, ge=1, le=100)
    """Maximum messages to include from history."""

    include_attachments: bool = True
    """Whether to include attachment context (if available)."""

    @property
    def channel_id(self) -> Optional[str]:
        """Extract channel_id from target if present."""
        if ":" in self.target:
            return self.target.split(":")[0]
        return None

    @property
    def thread_ts(self) -> Optional[str]:
        """Extract thread_ts from target if present."""
        if ":" in self.target:
            parts = self.target.split(":")
            return parts[1] if len(parts) > 1 else None
        return None

    @classmethod
    def for_extraction(
        cls,
        channel_id: str,
        thread_ts: str,
        budget: int = 4000,
    ) -> "ContextSpec":
        """Create spec for draft extraction."""
        return cls(
            mode=SuperMode.BUILD,
            target=f"{channel_id}:{thread_ts}",
            purpose="extract draft fields from conversation",
            budget_tokens=budget,
            required_artifacts=[],
            include_history=True,
        )

    @classmethod
    def for_review(
        cls,
        channel_id: str,
        thread_ts: str,
        budget: int = 6000,
    ) -> "ContextSpec":
        """Create spec for review/analysis."""
        return cls(
            mode=SuperMode.THINK,
            target=f"{channel_id}:{thread_ts}",
            purpose="analyze and provide review",
            budget_tokens=budget,
            required_artifacts=["review_artifact", "decisions"],
            include_history=True,
        )

    @classmethod
    def for_ops_explain(
        cls,
        channel_id: str,
        thread_ts: str,
    ) -> "ContextSpec":
        """Create spec for OPS explain mode."""
        return cls(
            mode=SuperMode.OPERATE,
            target=f"{channel_id}:{thread_ts}",
            purpose="explain bot reasoning and decisions",
            budget_tokens=3000,
            required_artifacts=["review_artifact", "decisions"],
            include_history=True,
            history_limit=10,
        )
