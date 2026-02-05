"""Base class for SuperMode handlers.

Ref: BOT_DESIGN.md - Four SuperModes
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.domain.channel import ChannelAggregate
from src.domain.entities import Entity
from src.intent.schemas import IntentClassification, SafetyCheckResult


@dataclass
class ModeContext:
    """Context passed to mode handlers."""

    # Message info
    message: str
    user_id: str
    channel_id: str
    thread_ts: str | None

    # Classification
    intent: IntentClassification
    safety_check: SafetyCheckResult

    # Additional context
    thread_messages: list[dict] = field(default_factory=list)
    entity_data: dict | None = None

    # Entity lifecycle (Phase 4)
    channel_aggregate: ChannelAggregate | None = None
    target_entity: Entity | None = None

    # Plan execution context (for multi-step plans)
    plan_step_context: str | None = None  # Output from previous plan steps
    is_plan_step: bool = False  # True when executing as part of a plan


@dataclass
class ModeResult:
    """Result from a mode handler."""

    # Response
    response_text: str
    response_blocks: list[dict] | None = None

    # Actions taken
    entity_created: str | None = None  # Entity ID if created
    entity_modified: str | None = None  # Entity ID if modified
    events_emitted: list[str] = field(default_factory=list)  # Event types emitted

    # State
    requires_confirmation: bool = False
    confirmation_data: dict | None = None

    # Entity lifecycle (Phase 4)
    draft_entity: Entity | None = None  # For preview before proposing


class ModeHandler(ABC):
    """Abstract base class for SuperMode handlers.

    Each handler implements the logic for one SuperMode.
    """

    @abstractmethod
    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle the message in this mode.

        Args:
            context: Mode context with message and classification info

        Returns:
            ModeResult with response and actions taken
        """
        pass

    @property
    @abstractmethod
    def mode_name(self) -> str:
        """Return the mode name for logging."""
        pass
