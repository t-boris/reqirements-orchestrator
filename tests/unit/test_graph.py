"""
Unit tests for the requirements graph.
"""

import pytest
from src.core.graph.graph import RequirementsGraph
from src.core.graph.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    NodeStatus,
    EdgeType,
)


class TestRequirementsGraph:
    """Tests for RequirementsGraph class."""

    def test_create_empty_graph(self):
        """Test creating an empty graph."""
        graph = RequirementsGraph(channel_id="test-channel")

        assert graph.channel_id == "test-channel"
        assert len(graph) == 0
        assert graph.get_all_nodes() == []
        assert graph.get_all_edges() == []

    def test_add_node(self):
        """Test adding a node to the graph."""
        graph = RequirementsGraph(channel_id="test")

        node = GraphNode(
            id="node-1",
            type=NodeType.STORY,
            title="Test Story",
            description="A test story",
        )

        result = graph.add_node(node)

        assert result.id == "node-1"
        assert len(graph) == 1
        assert graph.get_node("node-1") == node

    def test_add_node_generates_id(self):
        """Test that add_node generates ID if not provided."""
        graph = RequirementsGraph(channel_id="test")

        node = GraphNode(
            id="",
            type=NodeType.STORY,
            title="Test Story",
        )

        result = graph.add_node(node)

        assert result.id != ""
        assert len(result.id) == 8

    def test_add_duplicate_node_raises(self):
        """Test that adding a duplicate node raises ValueError."""
        graph = RequirementsGraph(channel_id="test")

        node = GraphNode(id="node-1", type=NodeType.STORY, title="Test")
        graph.add_node(node)

        with pytest.raises(ValueError, match="already exists"):
            graph.add_node(node)

    def test_update_node(self):
        """Test updating node attributes."""
        graph = RequirementsGraph(channel_id="test")

        node = GraphNode(
            id="node-1",
            type=NodeType.STORY,
            title="Original Title",
        )
        graph.add_node(node)

        updated = graph.update_node("node-1", title="Updated Title")

        assert updated.title == "Updated Title"
        assert graph.get_node("node-1").title == "Updated Title"

    def test_update_nonexistent_node_raises(self):
        """Test that updating a nonexistent node raises ValueError."""
        graph = RequirementsGraph(channel_id="test")

        with pytest.raises(ValueError, match="not found"):
            graph.update_node("nonexistent", title="Test")

    def test_delete_node(self):
        """Test deleting a node."""
        graph = RequirementsGraph(channel_id="test")

        node = GraphNode(id="node-1", type=NodeType.STORY, title="Test")
        graph.add_node(node)

        result = graph.delete_node("node-1")

        assert result is True
        assert len(graph) == 0
        assert graph.get_node("node-1") is None

    def test_delete_nonexistent_node(self):
        """Test deleting a nonexistent node returns False."""
        graph = RequirementsGraph(channel_id="test")

        result = graph.delete_node("nonexistent")

        assert result is False

    def test_add_edge(self):
        """Test adding an edge between nodes."""
        graph = RequirementsGraph(channel_id="test")

        node1 = GraphNode(id="n1", type=NodeType.EPIC, title="Epic")
        node2 = GraphNode(id="n2", type=NodeType.STORY, title="Story")
        graph.add_node(node1)
        graph.add_node(node2)

        edge = GraphEdge(
            source_id="n1",
            target_id="n2",
            type=EdgeType.DECOMPOSES_TO,
        )
        result = graph.add_edge(edge)

        assert result == edge
        assert len(graph.get_all_edges()) == 1

    def test_add_edge_missing_node_raises(self):
        """Test that adding edge with missing node raises ValueError."""
        graph = RequirementsGraph(channel_id="test")

        node = GraphNode(id="n1", type=NodeType.STORY, title="Story")
        graph.add_node(node)

        edge = GraphEdge(
            source_id="n1",
            target_id="nonexistent",
            type=EdgeType.DEPENDS_ON,
        )

        with pytest.raises(ValueError, match="not found"):
            graph.add_edge(edge)

    def test_cyclic_dependency_raises(self):
        """Test that cyclic dependencies are rejected."""
        graph = RequirementsGraph(channel_id="test")

        # Create nodes
        for i in range(3):
            graph.add_node(GraphNode(
                id=f"n{i}",
                type=NodeType.STORY,
                title=f"Story {i}",
            ))

        # Create chain: n0 -> n1 -> n2
        graph.add_edge(GraphEdge(
            source_id="n0", target_id="n1", type=EdgeType.DEPENDS_ON
        ))
        graph.add_edge(GraphEdge(
            source_id="n1", target_id="n2", type=EdgeType.DEPENDS_ON
        ))

        # Try to close the cycle: n2 -> n0
        with pytest.raises(ValueError, match="cycle"):
            graph.add_edge(GraphEdge(
                source_id="n2", target_id="n0", type=EdgeType.DEPENDS_ON
            ))

    def test_find_orphan_nodes(self):
        """Test finding orphan nodes."""
        graph = RequirementsGraph(channel_id="test")

        # Epic with child story (not orphan)
        graph.add_node(GraphNode(id="epic", type=NodeType.EPIC, title="Epic"))
        graph.add_node(GraphNode(id="story1", type=NodeType.STORY, title="Story 1"))
        graph.add_edge(GraphEdge(
            source_id="epic", target_id="story1", type=EdgeType.DECOMPOSES_TO
        ))

        # Orphan story (no parent)
        graph.add_node(GraphNode(id="story2", type=NodeType.STORY, title="Story 2"))

        orphans = graph.find_orphan_nodes()

        assert len(orphans) == 1
        assert orphans[0].id == "story2"

    def test_calculate_metrics(self):
        """Test calculating graph metrics."""
        graph = RequirementsGraph(channel_id="test")

        # Add a complete story (has AC, actor, component)
        graph.add_node(GraphNode(
            id="story1",
            type=NodeType.STORY,
            title="Story 1",
            attributes={
                "acceptance_criteria": ["AC1"],
                "actor": "User",
            },
        ))
        graph.add_node(GraphNode(id="comp", type=NodeType.COMPONENT, title="Comp"))
        graph.add_edge(GraphEdge(
            source_id="story1", target_id="comp", type=EdgeType.REQUIRES_COMPONENT
        ))

        # Add an incomplete story
        graph.add_node(GraphNode(id="story2", type=NodeType.STORY, title="Story 2"))

        metrics = graph.calculate_metrics()

        assert metrics["total_nodes"] == 3
        assert metrics["total_edges"] == 1
        assert metrics["completeness_score"] == 50.0  # 1/2 stories complete

    def test_to_context_string(self, sample_graph: RequirementsGraph):
        """Test converting graph to context string."""
        context = sample_graph.to_context_string()

        assert "Requirements Graph" in context
        assert "GOAL" in context
        assert "EPIC" in context
        assert "STORY" in context
        assert "COMPONENT" in context
        assert "RELATIONSHIPS" in context

    def test_serialization(self, sample_graph: RequirementsGraph):
        """Test graph serialization and deserialization."""
        # Serialize
        data = sample_graph.to_dict()

        assert data["channel_id"] == "test-channel"
        assert len(data["nodes"]) == 4
        assert len(data["edges"]) == 3

        # Deserialize
        restored = RequirementsGraph.from_dict(data)

        assert restored.channel_id == sample_graph.channel_id
        assert len(restored) == len(sample_graph)
        assert len(restored.get_all_edges()) == len(sample_graph.get_all_edges())
