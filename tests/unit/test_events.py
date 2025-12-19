"""
Unit tests for the event store.
"""

import pytest
from src.core.events.store import EventStore
from src.core.events.models import (
    Event,
    EventType,
    create_event,
    NodeCreatedEvent,
)
from src.core.graph.models import NodeType


class TestEventStore:
    """Tests for EventStore class."""

    def test_append_event(self, event_store: EventStore):
        """Test appending an event to the store."""
        event = create_event(
            EventType.NODE_CREATED,
            channel_id="test-channel",
            user_id="user-1",
            node_id="node-1",
            node_type="story",
            title="Test Story",
        )

        result = event_store.append(event)

        assert result.sequence == 1
        assert event_store.get_latest_sequence("test-channel") == 1

    def test_append_increments_sequence(self, event_store: EventStore):
        """Test that appending events increments sequence."""
        channel = "test-channel"

        for i in range(3):
            event = create_event(
                EventType.NODE_CREATED,
                channel_id=channel,
                user_id="user-1",
                node_id=f"node-{i}",
                node_type="story",
            )
            event_store.append(event)

        assert event_store.get_latest_sequence(channel) == 3

    def test_get_events(self, event_store: EventStore):
        """Test retrieving events from the store."""
        channel = "test-channel"

        # Add some events
        for i in range(5):
            event_store.append(create_event(
                EventType.NODE_CREATED,
                channel_id=channel,
                user_id="user-1",
                node_id=f"node-{i}",
                node_type="story",
            ))

        events = event_store.get_events(channel)

        assert len(events) == 5
        assert all(e.channel_id == channel for e in events)

    def test_get_events_since_sequence(self, event_store: EventStore):
        """Test retrieving events after a sequence number."""
        channel = "test-channel"

        for i in range(5):
            event_store.append(create_event(
                EventType.NODE_CREATED,
                channel_id=channel,
                user_id="user-1",
                node_id=f"node-{i}",
                node_type="story",
            ))

        events = event_store.get_events(channel, since_sequence=2)

        assert len(events) == 3
        assert events[0].sequence == 3

    def test_get_events_filter_by_type(self, event_store: EventStore):
        """Test filtering events by type."""
        channel = "test-channel"

        # Mix of event types
        event_store.append(create_event(
            EventType.NODE_CREATED, channel_id=channel, user_id="u1",
            node_id="n1", node_type="story",
        ))
        event_store.append(create_event(
            EventType.NODE_UPDATED, channel_id=channel, user_id="u1",
            node_id="n1", changes={"title": "Updated"},
        ))
        event_store.append(create_event(
            EventType.NODE_CREATED, channel_id=channel, user_id="u1",
            node_id="n2", node_type="story",
        ))

        events = event_store.get_events(
            channel,
            event_types=[EventType.NODE_CREATED],
        )

        assert len(events) == 2
        assert all(e.type == EventType.NODE_CREATED for e in events)

    def test_replay_graph(self, event_store: EventStore):
        """Test replaying events to reconstruct graph."""
        channel = "test-channel"

        # Create nodes
        event_store.append(create_event(
            EventType.NODE_CREATED,
            channel_id=channel,
            user_id="u1",
            node_id="epic-1",
            node_type="epic",
            title="Epic 1",
        ))
        event_store.append(create_event(
            EventType.NODE_CREATED,
            channel_id=channel,
            user_id="u1",
            node_id="story-1",
            node_type="story",
            title="Story 1",
        ))

        # Create edge
        event_store.append(create_event(
            EventType.EDGE_CREATED,
            channel_id=channel,
            user_id="u1",
            source_id="epic-1",
            target_id="story-1",
            edge_type="decomposes_to",
        ))

        # Replay
        graph = event_store.replay(channel)

        assert len(graph) == 2
        assert len(graph.get_all_edges()) == 1
        assert graph.get_node("epic-1") is not None
        assert graph.get_node("story-1") is not None

    def test_replay_with_updates(self, event_store: EventStore):
        """Test replaying with node updates."""
        channel = "test-channel"

        # Create node
        event_store.append(create_event(
            EventType.NODE_CREATED,
            channel_id=channel,
            user_id="u1",
            node_id="n1",
            node_type="story",
            title="Original Title",
        ))

        # Update node
        event_store.append(create_event(
            EventType.NODE_UPDATED,
            channel_id=channel,
            user_id="u1",
            node_id="n1",
            changes={"title": "Updated Title"},
        ))

        graph = event_store.replay(channel)
        node = graph.get_node("n1")

        assert node.title == "Updated Title"

    def test_replay_with_deletions(self, event_store: EventStore):
        """Test replaying with node deletions."""
        channel = "test-channel"

        # Create nodes
        event_store.append(create_event(
            EventType.NODE_CREATED,
            channel_id=channel, user_id="u1",
            node_id="n1", node_type="story", title="Keep",
        ))
        event_store.append(create_event(
            EventType.NODE_CREATED,
            channel_id=channel, user_id="u1",
            node_id="n2", node_type="story", title="Delete",
        ))

        # Delete one
        event_store.append(create_event(
            EventType.NODE_DELETED,
            channel_id=channel, user_id="u1",
            node_id="n2", node_type="story",
        ))

        graph = event_store.replay(channel)

        assert len(graph) == 1
        assert graph.get_node("n1") is not None
        assert graph.get_node("n2") is None

    def test_clear_channel(self, event_store: EventStore):
        """Test clearing all events for a channel."""
        channel = "test-channel"

        for i in range(5):
            event_store.append(create_event(
                EventType.NODE_CREATED,
                channel_id=channel, user_id="u1",
                node_id=f"n{i}", node_type="story",
            ))

        cleared = event_store.clear_channel(channel)

        assert cleared == 5
        assert event_store.get_latest_sequence(channel) == 0
        assert len(event_store.get_events(channel)) == 0

    def test_subscriber_notification(self, event_store: EventStore):
        """Test that subscribers are notified of new events."""
        received_events = []

        def callback(event: Event):
            received_events.append(event)

        event_store.subscribe(callback)

        event_store.append(create_event(
            EventType.NODE_CREATED,
            channel_id="test", user_id="u1",
            node_id="n1", node_type="story",
        ))

        assert len(received_events) == 1
        assert received_events[0].type == EventType.NODE_CREATED


class TestEventModels:
    """Tests for event model creation."""

    def test_create_node_created_event(self):
        """Test creating a node created event."""
        event = create_event(
            EventType.NODE_CREATED,
            channel_id="ch1",
            user_id="u1",
            node_id="n1",
            node_type="story",
            title="Test",
        )

        assert isinstance(event, NodeCreatedEvent)
        assert event.type == EventType.NODE_CREATED
        assert event.payload["node_id"] == "n1"
        assert event.payload["title"] == "Test"

    def test_events_are_immutable(self):
        """Test that events are frozen (immutable)."""
        event = create_event(
            EventType.NODE_CREATED,
            channel_id="ch1",
            user_id="u1",
            node_id="n1",
            node_type="story",
        )

        # Pydantic frozen models raise on attribute assignment
        with pytest.raises(Exception):
            event.channel_id = "different"
