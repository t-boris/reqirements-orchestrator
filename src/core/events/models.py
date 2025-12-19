"""
Event models for event sourcing.

All graph mutations are captured as immutable events, enabling full replay
and audit trail capabilities.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of events in the event store."""

    # Node events
    NODE_CREATED = "node_created"
    NODE_UPDATED = "node_updated"
    NODE_DELETED = "node_deleted"

    # Edge events
    EDGE_CREATED = "edge_created"
    EDGE_DELETED = "edge_deleted"

    # Graph events
    GRAPH_CLEARED = "graph_cleared"

    # Sync events
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"


class Event(BaseModel):
    """
    Base event model.

    All events are immutable records of state changes.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: EventType = Field(description="Event type discriminator")
    channel_id: str = Field(description="Slack channel this event belongs to")
    user_id: str = Field(default="", description="Slack user who triggered the event")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    sequence: int = Field(default=0, description="Event sequence number for ordering")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")

    class Config:
        frozen = True  # Events are immutable


class NodeCreatedEvent(Event):
    """Event: A new node was added to the graph."""

    type: EventType = EventType.NODE_CREATED
    # payload contains: node_id, node_type, title, description, attributes


class NodeUpdatedEvent(Event):
    """Event: An existing node was modified."""

    type: EventType = EventType.NODE_UPDATED
    # payload contains: node_id, changes (dict of field -> new_value)


class NodeDeletedEvent(Event):
    """Event: A node was removed from the graph."""

    type: EventType = EventType.NODE_DELETED
    # payload contains: node_id, node_type (for audit)


class EdgeCreatedEvent(Event):
    """Event: A new edge was added to the graph."""

    type: EventType = EventType.EDGE_CREATED
    # payload contains: source_id, target_id, edge_type, attributes


class EdgeDeletedEvent(Event):
    """Event: An edge was removed from the graph."""

    type: EventType = EventType.EDGE_DELETED
    # payload contains: source_id, target_id, edge_type


class GraphClearedEvent(Event):
    """Event: The entire graph was cleared (/req-clean)."""

    type: EventType = EventType.GRAPH_CLEARED
    # payload contains: node_count, edge_count (for audit)


class SyncStartedEvent(Event):
    """Event: Sync to external tracker initiated."""

    type: EventType = EventType.SYNC_STARTED
    # payload contains: target_system, node_ids


class SyncCompletedEvent(Event):
    """Event: Sync completed successfully."""

    type: EventType = EventType.SYNC_COMPLETED
    # payload contains: target_system, synced_items (node_id -> external_ref)


class SyncFailedEvent(Event):
    """Event: Sync failed (partial or complete)."""

    type: EventType = EventType.SYNC_FAILED
    # payload contains: target_system, error, synced_items, failed_items


def create_event(
    event_type: EventType,
    channel_id: str,
    user_id: str = "",
    **payload: Any,
) -> Event:
    """
    Factory function to create typed events.

    Args:
        event_type: The type of event to create.
        channel_id: Slack channel ID.
        user_id: Slack user ID who triggered the event.
        **payload: Event-specific data.

    Returns:
        Appropriate Event subclass instance.
    """
    event_classes = {
        EventType.NODE_CREATED: NodeCreatedEvent,
        EventType.NODE_UPDATED: NodeUpdatedEvent,
        EventType.NODE_DELETED: NodeDeletedEvent,
        EventType.EDGE_CREATED: EdgeCreatedEvent,
        EventType.EDGE_DELETED: EdgeDeletedEvent,
        EventType.GRAPH_CLEARED: GraphClearedEvent,
        EventType.SYNC_STARTED: SyncStartedEvent,
        EventType.SYNC_COMPLETED: SyncCompletedEvent,
        EventType.SYNC_FAILED: SyncFailedEvent,
    }

    event_class = event_classes.get(event_type, Event)
    return event_class(
        channel_id=channel_id,
        user_id=user_id,
        payload=payload,
    )
