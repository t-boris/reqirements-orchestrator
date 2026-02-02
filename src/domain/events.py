"""Domain events with schema versioning for event sourcing.

This module defines the event vocabulary that captures all state changes in the system.
All events are immutable (frozen) Pydantic models with schema versioning support.

Based on spec Part 4: Event Sourcing (maro_2_0.md).
"""

from datetime import datetime
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# Type aliases for domain identifiers
# These will be replaced with proper types from types.py once 01-02 is executed
ChannelId = str
ThreadTs = str
UserId = str
EntityId = str
JiraKey = str


class DomainEvent(BaseModel):
    """Base for all domain events with schema versioning.

    All domain events are immutable and include:
    - Schema versioning for forward compatibility
    - Correlation/causation IDs for distributed tracing
    - Standard metadata (event_id, timestamp, actor)

    Based on spec 4.1 and RESEARCH.md schema versioning patterns.
    """

    model_config = ConfigDict(frozen=True)

    # From RESEARCH.md - schema versioning from day one
    schema_version: ClassVar[int] = 1

    # From spec 4.1
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    aggregate_id: ChannelId  # Channel is aggregate root
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor_id: UserId
    version: int  # Sequence within aggregate

    # From RESEARCH.md - correlation/causation for tracing
    correlation_id: str | None = None
    causation_id: str | None = None

    @property
    def event_type(self) -> str:
        """Return the event class name as the event type."""
        return self.__class__.__name__

    def model_dump_with_type(self) -> dict[str, Any]:
        """Serialize with event_type and schema_version for storage."""
        data = self.model_dump()
        data["event_type"] = self.event_type
        data["schema_version"] = self.schema_version
        return data
