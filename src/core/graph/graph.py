"""
Requirements Graph - NetworkX-based knowledge graph implementation.

Provides the core data structure for storing and manipulating requirements.
"""

from datetime import datetime
from typing import Iterator
from uuid import uuid4

import networkx as nx

from src.core.graph.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeStatus,
    NodeType,
)


class RequirementsGraph:
    """
    NetworkX-based graph for managing requirements.

    Wraps nx.DiGraph with domain-specific operations and validation.
    Thread-safe for concurrent read operations.
    """

    def __init__(self, channel_id: str) -> None:
        """
        Initialize a new requirements graph.

        Args:
            channel_id: Slack channel ID this graph belongs to.
        """
        self.channel_id = channel_id
        self._graph = nx.DiGraph()
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    # -------------------------------------------------------------------------
    # Node Operations
    # -------------------------------------------------------------------------

    def add_node(self, node: GraphNode) -> GraphNode:
        """
        Add a node to the graph.

        Args:
            node: The node to add.

        Returns:
            The added node (with generated ID if not provided).

        Raises:
            ValueError: If node with same ID already exists.
        """
        if not node.id:
            node.id = str(uuid4())[:8]

        if self._graph.has_node(node.id):
            raise ValueError(f"Node with ID '{node.id}' already exists")

        self._graph.add_node(node.id, data=node)
        self._mark_updated()
        return node

    def get_node(self, node_id: str) -> GraphNode | None:
        """
        Get a node by ID.

        Args:
            node_id: The node identifier.

        Returns:
            The node if found, None otherwise.
        """
        if not self._graph.has_node(node_id):
            return None
        return self._graph.nodes[node_id].get("data")

    def update_node(self, node_id: str, **updates: object) -> GraphNode:
        """
        Update node attributes.

        Args:
            node_id: The node to update.
            **updates: Attributes to update.

        Returns:
            The updated node.

        Raises:
            ValueError: If node doesn't exist.
        """
        node = self.get_node(node_id)
        if not node:
            raise ValueError(f"Node '{node_id}' not found")

        for key, value in updates.items():
            if hasattr(node, key):
                setattr(node, key, value)
            else:
                node.attributes[key] = value

        node.updated_at = datetime.utcnow()
        self._graph.nodes[node_id]["data"] = node
        self._mark_updated()
        return node

    def delete_node(self, node_id: str) -> bool:
        """
        Remove a node and all its edges.

        Args:
            node_id: The node to remove.

        Returns:
            True if removed, False if not found.
        """
        if not self._graph.has_node(node_id):
            return False
        self._graph.remove_node(node_id)
        self._mark_updated()
        return True

    def get_all_nodes(self) -> list[GraphNode]:
        """Get all nodes in the graph."""
        return [data["data"] for _, data in self._graph.nodes(data=True) if "data" in data]

    def get_nodes_by_type(self, node_type: NodeType) -> list[GraphNode]:
        """Get all nodes of a specific type."""
        return [n for n in self.get_all_nodes() if n.type == node_type]

    def get_nodes_by_status(self, status: NodeStatus) -> list[GraphNode]:
        """Get all nodes with a specific status."""
        return [n for n in self.get_all_nodes() if n.status == status]

    # -------------------------------------------------------------------------
    # Edge Operations
    # -------------------------------------------------------------------------

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        """
        Add an edge to the graph.

        Args:
            edge: The edge to add.

        Returns:
            The added edge.

        Raises:
            ValueError: If source or target node doesn't exist.
            ValueError: If edge creates a cycle (for DEPENDS_ON).
        """
        if not self._graph.has_node(edge.source_id):
            raise ValueError(f"Source node '{edge.source_id}' not found")
        if not self._graph.has_node(edge.target_id):
            raise ValueError(f"Target node '{edge.target_id}' not found")

        # Check for cycles in dependency edges
        if edge.type == EdgeType.DEPENDS_ON:
            self._graph.add_edge(edge.source_id, edge.target_id, data=edge)
            if not nx.is_directed_acyclic_graph(self._graph):
                self._graph.remove_edge(edge.source_id, edge.target_id)
                raise ValueError("Edge would create a cycle in dependencies")
        else:
            self._graph.add_edge(edge.source_id, edge.target_id, data=edge)

        self._mark_updated()
        return edge

    def get_edge(self, source_id: str, target_id: str) -> GraphEdge | None:
        """Get an edge between two nodes."""
        if not self._graph.has_edge(source_id, target_id):
            return None
        return self._graph.edges[source_id, target_id].get("data")

    def delete_edge(self, source_id: str, target_id: str) -> bool:
        """Remove an edge between two nodes."""
        if not self._graph.has_edge(source_id, target_id):
            return False
        self._graph.remove_edge(source_id, target_id)
        self._mark_updated()
        return True

    def get_all_edges(self) -> list[GraphEdge]:
        """Get all edges in the graph."""
        return [
            data["data"]
            for _, _, data in self._graph.edges(data=True)
            if "data" in data
        ]

    def get_edges_by_type(self, edge_type: EdgeType) -> list[GraphEdge]:
        """Get all edges of a specific type."""
        return [e for e in self.get_all_edges() if e.type == edge_type]

    def get_outgoing_edges(self, node_id: str) -> list[GraphEdge]:
        """Get all edges originating from a node."""
        if not self._graph.has_node(node_id):
            return []
        return [
            self._graph.edges[node_id, target]["data"]
            for target in self._graph.successors(node_id)
            if "data" in self._graph.edges[node_id, target]
        ]

    def get_incoming_edges(self, node_id: str) -> list[GraphEdge]:
        """Get all edges pointing to a node."""
        if not self._graph.has_node(node_id):
            return []
        return [
            self._graph.edges[source, node_id]["data"]
            for source in self._graph.predecessors(node_id)
            if "data" in self._graph.edges[source, node_id]
        ]

    # -------------------------------------------------------------------------
    # Validation & Metrics
    # -------------------------------------------------------------------------

    def find_orphan_nodes(self) -> list[GraphNode]:
        """
        Find nodes without parent relationships (potential errors).

        Stories should have a parent EPIC, EPICs should have a parent GOAL.
        """
        orphans = []
        for node in self.get_all_nodes():
            if node.type in (NodeType.STORY, NodeType.SUBTASK):
                incoming = self.get_incoming_edges(node.id)
                has_parent = any(e.type == EdgeType.DECOMPOSES_TO for e in incoming)
                if not has_parent:
                    orphans.append(node)
        return orphans

    def find_unlinked_stories(self) -> list[GraphNode]:
        """Find stories without REQUIRES_COMPONENT link (magic stories)."""
        unlinked = []
        for node in self.get_nodes_by_type(NodeType.STORY):
            outgoing = self.get_outgoing_edges(node.id)
            has_component = any(e.type == EdgeType.REQUIRES_COMPONENT for e in outgoing)
            if not has_component:
                unlinked.append(node)
        return unlinked

    def find_conflicts(self) -> list[GraphEdge]:
        """Find all CONFLICTS_WITH edges (blockers for sync)."""
        return self.get_edges_by_type(EdgeType.CONFLICTS_WITH)

    def find_blocking_questions(self) -> list[tuple[GraphNode, GraphNode]]:
        """Find unanswered questions blocking stories."""
        blocking = []
        for edge in self.get_edges_by_type(EdgeType.BLOCKS):
            question = self.get_node(edge.source_id)
            story = self.get_node(edge.target_id)
            if question and story:
                if not question.attributes.get("answered", False):
                    blocking.append((question, story))
        return blocking

    def calculate_metrics(self) -> dict[str, float | int]:
        """
        Calculate graph quality metrics.

        Returns:
            Dict with completeness score, conflict ratio, orphan count, etc.
        """
        stories = self.get_nodes_by_type(NodeType.STORY)
        total_stories = len(stories)

        if total_stories == 0:
            return {
                "completeness_score": 0.0,
                "conflict_ratio": 0.0,
                "orphan_count": 0,
                "total_nodes": len(self.get_all_nodes()),
                "total_edges": len(self.get_all_edges()),
            }

        # Completeness: stories with AC, actor, and component
        complete = 0
        for story in stories:
            has_ac = bool(story.attributes.get("acceptance_criteria"))
            has_actor = bool(story.attributes.get("actor"))
            has_component = any(
                e.type == EdgeType.REQUIRES_COMPONENT
                for e in self.get_outgoing_edges(story.id)
            )
            if has_ac and has_actor and has_component:
                complete += 1

        edges = self.get_all_edges()
        conflicts = len(self.find_conflicts())

        return {
            "completeness_score": (complete / total_stories) * 100,
            "conflict_ratio": (conflicts / len(edges)) * 100 if edges else 0.0,
            "orphan_count": len(self.find_orphan_nodes()),
            "unlinked_stories": len(self.find_unlinked_stories()),
            "blocking_questions": len(self.find_blocking_questions()),
            "total_nodes": len(self.get_all_nodes()),
            "total_edges": len(edges),
        }

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_context_string(self) -> str:
        """
        Convert entire graph to text for LLM context injection.

        Returns:
            Human-readable representation of the graph state.
        """
        lines = [f"=== Requirements Graph (Channel: {self.channel_id}) ===\n"]

        # Group nodes by type
        for node_type in NodeType:
            nodes = self.get_nodes_by_type(node_type)
            if nodes:
                lines.append(f"\n--- {node_type.value.upper()}S ---")
                for node in nodes:
                    lines.append(node.to_context_string())

        # Add edges
        edges = self.get_all_edges()
        if edges:
            lines.append("\n--- RELATIONSHIPS ---")
            for edge in edges:
                lines.append(edge.to_context_string())

        # Add metrics summary
        metrics = self.calculate_metrics()
        lines.append("\n--- METRICS ---")
        lines.append(f"Completeness: {metrics['completeness_score']:.1f}%")
        lines.append(f"Orphans: {metrics['orphan_count']}")
        lines.append(f"Conflicts: {metrics['conflict_ratio']:.1f}%")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize graph to dictionary for persistence."""
        return {
            "channel_id": self.channel_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "nodes": [node.model_dump() for node in self.get_all_nodes()],
            "edges": [edge.model_dump() for edge in self.get_all_edges()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RequirementsGraph":
        """Deserialize graph from dictionary."""
        graph = cls(channel_id=data["channel_id"])
        graph.created_at = datetime.fromisoformat(data["created_at"])
        graph.updated_at = datetime.fromisoformat(data["updated_at"])

        # Add nodes first
        for node_data in data.get("nodes", []):
            node = GraphNode.model_validate(node_data)
            graph._graph.add_node(node.id, data=node)

        # Then add edges
        for edge_data in data.get("edges", []):
            edge = GraphEdge.model_validate(edge_data)
            graph._graph.add_edge(edge.source_id, edge.target_id, data=edge)

        return graph

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _mark_updated(self) -> None:
        """Update the graph's timestamp."""
        self.updated_at = datetime.utcnow()

    def __len__(self) -> int:
        """Return number of nodes."""
        return self._graph.number_of_nodes()

    def __iter__(self) -> Iterator[GraphNode]:
        """Iterate over all nodes."""
        return iter(self.get_all_nodes())
