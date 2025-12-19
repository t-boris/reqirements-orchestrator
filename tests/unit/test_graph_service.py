"""
Unit tests for the graph service.
"""

import pytest
from src.core.services.graph_service import GraphService
from src.core.events.store import EventStore
from src.core.graph.models import NodeType, NodeStatus, EdgeType


class TestGraphService:
    """Tests for GraphService class."""

    def test_get_or_create_graph(self, graph_service: GraphService, test_channel_id: str):
        """Test getting or creating a graph."""
        # First call creates
        graph1 = graph_service.get_or_create_graph(test_channel_id)

        assert graph1.channel_id == test_channel_id

        # Second call returns same graph
        graph2 = graph_service.get_or_create_graph(test_channel_id)

        assert graph1 is graph2

    def test_add_node(
        self,
        graph_service: GraphService,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test adding a node through the service."""
        node = graph_service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.STORY,
            title="Test Story",
            description="A test",
            actor="User",
        )

        assert node.id is not None
        assert node.type == NodeType.STORY
        assert node.title == "Test Story"
        assert node.attributes.get("actor") == "User"

        # Verify in graph
        graph = graph_service.get_or_create_graph(test_channel_id)
        assert graph.get_node(node.id) is not None

    def test_update_node(
        self,
        graph_service: GraphService,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test updating a node through the service."""
        # Create node
        node = graph_service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.STORY,
            title="Original",
        )

        # Update it
        updated = graph_service.update_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_id=node.id,
            title="Updated",
            status=NodeStatus.APPROVED,
        )

        assert updated.title == "Updated"
        assert updated.status == NodeStatus.APPROVED

    def test_delete_node(
        self,
        graph_service: GraphService,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test deleting a node through the service."""
        node = graph_service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.STORY,
            title="To Delete",
        )

        result = graph_service.delete_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_id=node.id,
        )

        assert result is True

        graph = graph_service.get_or_create_graph(test_channel_id)
        assert graph.get_node(node.id) is None

    def test_add_edge(
        self,
        graph_service: GraphService,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test adding an edge through the service."""
        # Create nodes
        epic = graph_service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.EPIC,
            title="Epic",
        )
        story = graph_service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.STORY,
            title="Story",
        )

        # Add edge
        edge = graph_service.add_edge(
            channel_id=test_channel_id,
            user_id=test_user_id,
            source_id=epic.id,
            target_id=story.id,
            edge_type=EdgeType.DECOMPOSES_TO,
        )

        assert edge.source_id == epic.id
        assert edge.target_id == story.id
        assert edge.type == EdgeType.DECOMPOSES_TO

    def test_clear_graph(
        self,
        graph_service: GraphService,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test clearing the entire graph."""
        # Add some nodes
        for i in range(3):
            graph_service.add_node(
                channel_id=test_channel_id,
                user_id=test_user_id,
                node_type=NodeType.STORY,
                title=f"Story {i}",
            )

        result = graph_service.clear_graph(
            channel_id=test_channel_id,
            user_id=test_user_id,
        )

        assert result["nodes"] == 3

        graph = graph_service.get_or_create_graph(test_channel_id)
        assert len(graph) == 0

    def test_get_graph_state(
        self,
        graph_service: GraphService,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test getting graph state."""
        # Add nodes
        graph_service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.STORY,
            title="Story",
        )

        state = graph_service.get_graph_state(test_channel_id)

        assert state["channel_id"] == test_channel_id
        assert len(state["nodes"]) == 1
        assert "metrics" in state
        assert "updated_at" in state

    def test_validate_graph(
        self,
        graph_service: GraphService,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test graph validation."""
        # Add orphan story (no parent)
        graph_service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.STORY,
            title="Orphan Story",
        )

        issues = graph_service.validate_graph(test_channel_id)

        assert len(issues["orphan_nodes"]) == 1
        assert len(issues["unlinked_stories"]) == 1

    def test_events_recorded(
        self,
        event_store: EventStore,
        test_channel_id: str,
        test_user_id: str,
    ):
        """Test that operations record events."""
        service = GraphService(event_store)

        # Add node
        service.add_node(
            channel_id=test_channel_id,
            user_id=test_user_id,
            node_type=NodeType.STORY,
            title="Test",
        )

        events = event_store.get_events(test_channel_id)

        assert len(events) == 1
        assert events[0].type.value == "node_created"
