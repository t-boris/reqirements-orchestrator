"""
Event Store - Persistence and replay of events.

Provides append-only storage of events and capability to replay
the full history to reconstruct graph state.
"""

from collections import defaultdict
from datetime import datetime
from typing import Callable

from src.core.events.models import Event, EventType, create_event
from src.core.graph.graph import RequirementsGraph
from src.core.graph.models import EdgeType, GraphEdge, GraphNode, NodeType


class EventStore:
    """
    In-memory event store with replay capability.

    Events are stored per channel and can be replayed to reconstruct
    the graph state at any point in time.

    Note: For production, this is backed by PostgreSQL via the
    persistence adapter.
    """

    def __init__(self) -> None:
        """Initialize empty event store."""
        # channel_id -> list of events (ordered by sequence)
        self._events: dict[str, list[Event]] = defaultdict(list)
        # channel_id -> current sequence number
        self._sequences: dict[str, int] = defaultdict(int)
        # Subscribers for event notifications
        self._subscribers: list[Callable[[Event], None]] = []

    def append(self, event: Event) -> Event:
        """
        Append an event to the store.

        Args:
            event: The event to store.

        Returns:
            The event with sequence number assigned.
        """
        # Assign sequence number
        self._sequences[event.channel_id] += 1
        # Create new event with sequence (events are immutable)
        stored_event = event.model_copy(
            update={"sequence": self._sequences[event.channel_id]}
        )

        self._events[event.channel_id].append(stored_event)

        # Notify subscribers
        for subscriber in self._subscribers:
            subscriber(stored_event)

        return stored_event

    def get_events(
        self,
        channel_id: str,
        since_sequence: int = 0,
        event_types: list[EventType] | None = None,
    ) -> list[Event]:
        """
        Get events for a channel.

        Args:
            channel_id: The channel to get events for.
            since_sequence: Only return events after this sequence number.
            event_types: Filter by event types (None = all types).

        Returns:
            List of events matching the criteria.
        """
        events = self._events.get(channel_id, [])

        filtered = [e for e in events if e.sequence > since_sequence]

        if event_types:
            filtered = [e for e in filtered if e.type in event_types]

        return filtered

    def get_latest_sequence(self, channel_id: str) -> int:
        """Get the latest sequence number for a channel."""
        return self._sequences.get(channel_id, 0)

    def replay(self, channel_id: str, until_sequence: int | None = None) -> RequirementsGraph:
        """
        Replay events to reconstruct graph state.

        Args:
            channel_id: The channel to replay.
            until_sequence: Stop at this sequence (None = replay all).

        Returns:
            Reconstructed RequirementsGraph.
        """
        graph = RequirementsGraph(channel_id=channel_id)
        events = self._events.get(channel_id, [])

        for event in events:
            if until_sequence and event.sequence > until_sequence:
                break
            self._apply_event(graph, event)

        return graph

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        """
        Subscribe to event notifications.

        Args:
            callback: Function to call when new events are appended.
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        """Remove a subscriber."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def clear_channel(self, channel_id: str) -> int:
        """
        Clear all events for a channel.

        Args:
            channel_id: The channel to clear.

        Returns:
            Number of events cleared.
        """
        count = len(self._events.get(channel_id, []))
        self._events[channel_id] = []
        self._sequences[channel_id] = 0
        return count

    def _apply_event(self, graph: RequirementsGraph, event: Event) -> None:
        """
        Apply a single event to reconstruct graph state.

        Args:
            graph: The graph to modify.
            event: The event to apply.
        """
        payload = event.payload

        if event.type == EventType.NODE_CREATED:
            node = GraphNode(
                id=payload["node_id"],
                type=NodeType(payload["node_type"]),
                title=payload.get("title", ""),
                description=payload.get("description", ""),
                attributes=payload.get("attributes", {}),
                created_by=event.user_id,
            )
            graph._graph.add_node(node.id, data=node)

        elif event.type == EventType.NODE_UPDATED:
            node_id = payload["node_id"]
            if graph._graph.has_node(node_id):
                node = graph._graph.nodes[node_id]["data"]
                changes = payload.get("changes", {})
                for key, value in changes.items():
                    if hasattr(node, key):
                        setattr(node, key, value)
                    else:
                        node.attributes[key] = value
                node.updated_at = event.timestamp

        elif event.type == EventType.NODE_DELETED:
            node_id = payload["node_id"]
            if graph._graph.has_node(node_id):
                graph._graph.remove_node(node_id)

        elif event.type == EventType.EDGE_CREATED:
            edge = GraphEdge(
                source_id=payload["source_id"],
                target_id=payload["target_id"],
                type=EdgeType(payload["edge_type"]),
                attributes=payload.get("attributes", {}),
            )
            if (
                graph._graph.has_node(edge.source_id)
                and graph._graph.has_node(edge.target_id)
            ):
                graph._graph.add_edge(edge.source_id, edge.target_id, data=edge)

        elif event.type == EventType.EDGE_DELETED:
            source_id = payload["source_id"]
            target_id = payload["target_id"]
            if graph._graph.has_edge(source_id, target_id):
                graph._graph.remove_edge(source_id, target_id)

        elif event.type == EventType.GRAPH_CLEARED:
            graph._graph.clear()

    def to_dict(self, channel_id: str) -> dict:
        """Serialize events for a channel."""
        return {
            "channel_id": channel_id,
            "sequence": self._sequences.get(channel_id, 0),
            "events": [e.model_dump() for e in self._events.get(channel_id, [])],
        }

    def load_events(self, channel_id: str, events_data: list[dict]) -> None:
        """
        Load events from persistence.

        Args:
            channel_id: The channel these events belong to.
            events_data: List of serialized events.
        """
        events = [Event.model_validate(e) for e in events_data]
        self._events[channel_id] = events
        if events:
            self._sequences[channel_id] = events[-1].sequence
