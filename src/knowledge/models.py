"""Knowledge Graph models for entities and constraints."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class ConstraintStatus(str, Enum):
    """Status of a constraint/decision."""
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DEPRECATED = "deprecated"


class Constraint(BaseModel):
    """Structured constraint/decision from a thread.

    Structured format enables reliable contradiction detection:
    - Same subject + different value = conflict
    - Subject overlap = maybe conflict (flag for review)

    Example:
        subject: "API.date_format"
        value: "unix_timestamp"
        status: "accepted"
    """
    id: UUID = Field(default_factory=uuid4)
    epic_id: str  # Jira Epic key (e.g., "PROJ-50")
    thread_ts: str  # Source thread
    message_ts: Optional[str] = None  # Source message
    subject: str  # Dot-notation topic (e.g., "API.date_format")
    value: str  # The decision/constraint value
    status: ConstraintStatus = ConstraintStatus.PROPOSED
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class Entity(BaseModel):
    """Entity extracted from conversation.

    Entities are technical concepts mentioned in discussions:
    - Components: "login button", "API", "database"
    - Concepts: "authentication", "caching", "rate limiting"
    """
    id: UUID = Field(default_factory=uuid4)
    epic_id: str  # Linked Epic
    name: str  # Entity name
    entity_type: str  # Component, Concept, Person, etc.
    mentions: int = 1  # Number of times mentioned
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class Relationship(BaseModel):
    """Relationship between entities.

    Examples:
    - "login button" -> uses -> "authentication"
    - "API" -> returns -> "JSON"
    """
    id: UUID = Field(default_factory=uuid4)
    epic_id: str
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: str  # "uses", "returns", "depends_on", etc.
    created_at: datetime = Field(default_factory=datetime.utcnow)
