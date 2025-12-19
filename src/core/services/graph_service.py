"""
Graph Service - Core business logic for graph operations.

Provides a high-level API for manipulating the requirements graph,
with automatic event sourcing and validation.
"""

from typing import Any

from src.core.events.models import EventType, create_event
from src.core.events.store import EventStore
from src.core.graph.graph import RequirementsGraph
from src.core.graph.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeStatus,
    NodeType,
)


class GraphService:
    """
    Service layer for graph operations.

    All mutations go through this service to ensure:
    - Events are recorded for event sourcing
    - Validation rules are enforced
    - Metrics are updated
    """

    def __init__(self, event_store: EventStore) -> None:
        """
        Initialize graph service.

        Args:
            event_store: Event store for persistence.
        """
        self._event_store = event_store
        self._graphs: dict[str, RequirementsGraph] = {}

    def get_or_create_graph(self, channel_id: str) -> RequirementsGraph:
        """
        Get existing graph or create new one for channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            The requirements graph for this channel.
        """
        if channel_id not in self._graphs:
            # Try to replay from events
            graph = self._event_store.replay(channel_id)
            self._graphs[channel_id] = graph
        return self._graphs[channel_id]

    def add_node(
        self,
        channel_id: str,
        user_id: str,
        node_type: NodeType,
        title: str,
        description: str = "",
        **attributes: Any,
    ) -> GraphNode:
        """
        Add a new node to the graph.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered the action.
            node_type: Type of node (GOAL, EPIC, STORY, etc.).
            title: Node title.
            description: Node description.
            **attributes: Additional type-specific attributes.

        Returns:
            The created node.
        """
        graph = self.get_or_create_graph(channel_id)

        # Create node
        node = GraphNode(
            id="",  # Will be generated
            type=node_type,
            title=title,
            description=description,
            attributes=attributes,
            created_by=user_id,
        )
        node = graph.add_node(node)

        # Record event
        event = create_event(
            EventType.NODE_CREATED,
            channel_id=channel_id,
            user_id=user_id,
            node_id=node.id,
            node_type=node_type.value,
            title=title,
            description=description,
            attributes=attributes,
        )
        self._event_store.append(event)

        return node

    def update_node(
        self,
        channel_id: str,
        user_id: str,
        node_id: str,
        **changes: Any,
    ) -> GraphNode:
        """
        Update an existing node.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered the action.
            node_id: ID of node to update.
            **changes: Fields to update.

        Returns:
            The updated node.
        """
        graph = self.get_or_create_graph(channel_id)
        node = graph.update_node(node_id, **changes)

        # Record event
        event = create_event(
            EventType.NODE_UPDATED,
            channel_id=channel_id,
            user_id=user_id,
            node_id=node_id,
            changes=changes,
        )
        self._event_store.append(event)

        return node

    def delete_node(
        self,
        channel_id: str,
        user_id: str,
        node_id: str,
    ) -> bool:
        """
        Delete a node from the graph.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered the action.
            node_id: ID of node to delete.

        Returns:
            True if deleted, False if not found.
        """
        graph = self.get_or_create_graph(channel_id)
        node = graph.get_node(node_id)

        if not node:
            return False

        result = graph.delete_node(node_id)

        if result:
            event = create_event(
                EventType.NODE_DELETED,
                channel_id=channel_id,
                user_id=user_id,
                node_id=node_id,
                node_type=node.type.value,
            )
            self._event_store.append(event)

        return result

    def add_edge(
        self,
        channel_id: str,
        user_id: str,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        **attributes: Any,
    ) -> GraphEdge:
        """
        Add an edge between two nodes.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered the action.
            source_id: Source node ID.
            target_id: Target node ID.
            edge_type: Type of relationship.
            **attributes: Additional edge attributes.

        Returns:
            The created edge.

        Raises:
            ValueError: If nodes don't exist or edge creates cycle.
        """
        graph = self.get_or_create_graph(channel_id)

        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            type=edge_type,
            attributes=attributes,
        )
        edge = graph.add_edge(edge)

        event = create_event(
            EventType.EDGE_CREATED,
            channel_id=channel_id,
            user_id=user_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type.value,
            attributes=attributes,
        )
        self._event_store.append(event)

        return edge

    def delete_edge(
        self,
        channel_id: str,
        user_id: str,
        source_id: str,
        target_id: str,
    ) -> bool:
        """
        Delete an edge from the graph.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered the action.
            source_id: Source node ID.
            target_id: Target node ID.

        Returns:
            True if deleted, False if not found.
        """
        graph = self.get_or_create_graph(channel_id)
        edge = graph.get_edge(source_id, target_id)

        if not edge:
            return False

        result = graph.delete_edge(source_id, target_id)

        if result:
            event = create_event(
                EventType.EDGE_DELETED,
                channel_id=channel_id,
                user_id=user_id,
                source_id=source_id,
                target_id=target_id,
                edge_type=edge.type.value,
            )
            self._event_store.append(event)

        return result

    def clear_graph(self, channel_id: str, user_id: str) -> dict[str, int]:
        """
        Clear all nodes and edges from a graph (/req-clean).

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered the action.

        Returns:
            Dict with counts of cleared items.
        """
        graph = self.get_or_create_graph(channel_id)
        node_count = len(graph.get_all_nodes())
        edge_count = len(graph.get_all_edges())

        # Clear the graph
        graph._graph.clear()
        graph._mark_updated()

        # Record event
        event = create_event(
            EventType.GRAPH_CLEARED,
            channel_id=channel_id,
            user_id=user_id,
            node_count=node_count,
            edge_count=edge_count,
        )
        self._event_store.append(event)

        return {"nodes": node_count, "edges": edge_count}

    def get_graph_state(self, channel_id: str) -> dict:
        """
        Get current state of the graph.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Dict with graph data and metrics.
        """
        graph = self.get_or_create_graph(channel_id)
        return {
            "channel_id": channel_id,
            "nodes": [n.model_dump() for n in graph.get_all_nodes()],
            "edges": [e.model_dump() for e in graph.get_all_edges()],
            "metrics": graph.calculate_metrics(),
            "updated_at": graph.updated_at.isoformat(),
        }

    def get_context_string(self, channel_id: str) -> str:
        """
        Get graph as text for LLM context injection.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Human-readable graph representation.
        """
        graph = self.get_or_create_graph(channel_id)
        return graph.to_context_string()

    def validate_graph(self, channel_id: str) -> dict[str, list]:
        """
        Validate graph and return all issues.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Dict with validation issues by category.
        """
        graph = self.get_or_create_graph(channel_id)

        return {
            "orphan_nodes": [n.id for n in graph.find_orphan_nodes()],
            "unlinked_stories": [n.id for n in graph.find_unlinked_stories()],
            "conflicts": [
                {"source": e.source_id, "target": e.target_id}
                for e in graph.find_conflicts()
            ],
            "blocking_questions": [
                {"question": q.id, "story": s.id}
                for q, s in graph.find_blocking_questions()
            ],
        }

    def mark_nodes_synced(
        self,
        channel_id: str,
        user_id: str,
        node_ids: list[str],
        external_refs: dict[str, dict],
    ) -> None:
        """
        Mark nodes as synced with external references.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered sync.
            node_ids: IDs of synced nodes.
            external_refs: Map of node_id -> external reference data.
        """
        from src.core.graph.models import ExternalRef

        graph = self.get_or_create_graph(channel_id)

        for node_id in node_ids:
            ref_data = external_refs.get(node_id, {})
            if ref_data:
                external_ref = ExternalRef(**ref_data)
                self.update_node(
                    channel_id,
                    user_id,
                    node_id,
                    status=NodeStatus.SYNCED,
                    external_ref=external_ref,
                )
            else:
                self.update_node(
                    channel_id,
                    user_id,
                    node_id,
                    status=NodeStatus.SYNCED,
                )

    def mark_partial_sync(
        self,
        channel_id: str,
        user_id: str,
        failed_node_ids: list[str],
    ) -> None:
        """
        Mark nodes as partially synced after sync failure.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user who triggered sync.
            failed_node_ids: IDs of nodes that failed to sync.
        """
        for node_id in failed_node_ids:
            self.update_node(
                channel_id,
                user_id,
                node_id,
                status=NodeStatus.PARTIALLY_SYNCED,
            )
