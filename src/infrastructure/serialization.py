"""Event serialization and deserialization for event sourcing.

This module provides functions for serializing events to storage format
and deserializing them back to domain event objects.

Based on spec 4.4 and RESEARCH.md patterns.
"""

from typing import Any

from src.domain.events import (
    # Base class
    DomainEvent,
    # Work Item Events
    WorkItemDrafted,
    WorkItemProposed,
    WorkItemApproved,
    WorkItemCommitted,
    WorkItemUpdated,
    # Decision Events
    DecisionRecorded,
    DecisionProposed,
    DecisionApproved,
    DecisionCommitted,
    DecisionDeprecated,
    # Conflict Events
    ConflictDetected,
    ConflictResolved,
    # Process/Plan Events
    ProcessStarted,
    ProcessStageCompleted,
    ProcessCompleted,
    PlanCreated,
    PlanItemCompleted,
    PlanCompleted,
)

# =============================================================================
# Event Registry
# =============================================================================

EVENT_REGISTRY: dict[str, type[DomainEvent]] = {
    # Work Item Events
    "WorkItemDrafted": WorkItemDrafted,
    "WorkItemProposed": WorkItemProposed,
    "WorkItemApproved": WorkItemApproved,
    "WorkItemCommitted": WorkItemCommitted,
    "WorkItemUpdated": WorkItemUpdated,
    # Decision Events
    "DecisionRecorded": DecisionRecorded,
    "DecisionProposed": DecisionProposed,
    "DecisionApproved": DecisionApproved,
    "DecisionCommitted": DecisionCommitted,
    "DecisionDeprecated": DecisionDeprecated,
    # Conflict Events
    "ConflictDetected": ConflictDetected,
    "ConflictResolved": ConflictResolved,
    # Process/Plan Events
    "ProcessStarted": ProcessStarted,
    "ProcessStageCompleted": ProcessStageCompleted,
    "ProcessCompleted": ProcessCompleted,
    "PlanCreated": PlanCreated,
    "PlanItemCompleted": PlanItemCompleted,
    "PlanCompleted": PlanCompleted,
}


# =============================================================================
# Serialization Functions
# =============================================================================


def serialize_event(event: DomainEvent) -> dict[str, Any]:
    """Serialize event for storage.

    The serialized format includes:
    - All event fields via model_dump()
    - event_type: The class name for deserialization
    - schema_version: For future upcasting support

    Args:
        event: The domain event to serialize

    Returns:
        A dict suitable for JSON/JSONB storage
    """
    return event.model_dump_with_type()


def deserialize_event(data: dict[str, Any]) -> DomainEvent:
    """Deserialize event from storage.

    Uses the event_type field to look up the correct class in the registry,
    then validates and constructs the event using Pydantic.

    Schema versioning is handled by upcasting (not implemented yet - events
    are stored with schema_version for future evolution support).

    Args:
        data: The stored event data dict

    Returns:
        The reconstructed domain event

    Raises:
        KeyError: If event_type is not in the registry
        ValidationError: If the data doesn't match the event schema
    """
    # Extract metadata fields
    event_type = data.pop("event_type")
    data.pop("schema_version", None)  # Handled by upcasting when implemented

    # Look up the event class
    cls = EVENT_REGISTRY[event_type]

    # Validate and construct the event
    return cls.model_validate(data)


def get_event_types() -> list[str]:
    """Get all registered event type names.

    Returns:
        List of event type names that can be deserialized
    """
    return list(EVENT_REGISTRY.keys())


def is_registered_event_type(event_type: str) -> bool:
    """Check if an event type is registered.

    Args:
        event_type: The event type name to check

    Returns:
        True if the event type is in the registry
    """
    return event_type in EVENT_REGISTRY
