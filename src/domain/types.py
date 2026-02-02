"""Core domain types and value objects.

Part 3.1-3.3 of MARO 2.0 spec: Value objects, entity lifecycle, entity types.
"""

from enum import Enum
from typing import Annotated, Any, NewType
from uuid import uuid4

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


# === Value Objects (NewType or str subclass as in spec) ===

ChannelId = NewType("ChannelId", str)  # Slack channel ID
ThreadTs = NewType("ThreadTs", str)    # Slack thread timestamp
UserId = NewType("UserId", str)        # Slack user ID
JiraKey = NewType("JiraKey", str)      # Jira issue key (PROJ-123)
Version = NewType("Version", int)      # Entity version


class EntityId(str):
    """Unique entity identifier."""

    @classmethod
    def generate(cls) -> "EntityId":
        return cls(str(uuid4()))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Make EntityId Pydantic-compatible."""
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(),
            serialization=core_schema.to_string_ser_schema(),
        )


# === Enums ===

class EntityLifecycle(str, Enum):
    """Single lifecycle for all entities.

    Ref: Spec 3.2
    """
    DRAFT = "draft"           # Being formed in thread
    PROPOSED = "proposed"     # Visible in channel, awaiting approval
    APPROVED = "approved"     # Approved, ready for Jira projection
    COMMITTED = "committed"   # Projected to Jira
    DEPRECATED = "deprecated" # Superseded (decisions only)


class EntityType(str, Enum):
    """Type of entity.

    Ref: Spec 3.3
    """
    WORK_ITEM = "work_item"   # Epic, Story, Task, Bug, Spike
    DECISION = "decision"     # Architectural/scope/process decisions
    ARTIFACT = "artifact"     # Reviews, documents (future)


class SyncStatus(str, Enum):
    """Jira sync status.

    Ref: Spec 3.7
    """
    PENDING = "pending"       # Not yet synced
    SYNCED = "synced"         # Up to date
    CONFLICT = "conflict"     # Conflict detected
