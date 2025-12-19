"""
Graph data models for the requirements knowledge graph.

Defines node types, edge types, and their attributes according to the MARO ontology.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """
    Types of nodes in the requirements graph.

    Each type maps to a specific Jira issue type during sync.
    """

    GOAL = "goal"  # Global objective -> Jira Initiative/Theme
    EPIC = "epic"  # Large functional block -> Jira Epic
    STORY = "story"  # User story -> Jira Story
    SUBTASK = "subtask"  # Technical task -> Jira Sub-task
    COMPONENT = "component"  # Architectural component -> Jira Component
    CONSTRAINT = "constraint"  # NFR (Security, Performance) -> Jira Label/AC
    RISK = "risk"  # Identified risk -> Jira Linked Issue (Risk)
    QUESTION = "question"  # Open question (Gap) -> Jira Comment
    CONTEXT = "context"  # External documentation reference -> Jira Attachment


class NodeStatus(str, Enum):
    """Status of a node in the requirements' lifecycle."""

    DRAFT = "draft"  # Initial state, not validated
    APPROVED = "approved"  # Validated, ready for sync
    SYNCED = "synced"  # Successfully synced to issue tracker
    PARTIALLY_SYNCED = "partially_synced"  # Sync failed midway
    CONFLICT = "conflict"  # Has unresolved conflicts


class EdgeType(str, Enum):
    """
    Types of relationships between nodes.

    Defines the semantic meaning of connections in the graph.
    """

    DECOMPOSES_TO = "decomposes_to"  # GOAL -> EPIC -> STORY hierarchy
    DEPENDS_ON = "depends_on"  # Blocking dependency between stories
    REQUIRES_COMPONENT = "requires_component"  # Story -> Component technical link
    CONSTRAINED_BY = "constrained_by"  # Story -> Constraint NFR application
    CONFLICTS_WITH = "conflicts_with"  # Logical contradiction (blocks sync)
    MITIGATES = "mitigates"  # Story -> Risk mitigation measure
    BLOCKS = "blocks"  # Question -> Story information gap


class ExternalRef(BaseModel):
    """Reference to an external issue tracker item."""

    system: str = Field(description="External system name (jira, github)")
    id: str = Field(description="External ID (e.g., PROJ-123)")
    url: str = Field(default="", description="Direct URL to the item")


class GraphNode(BaseModel):
    """
    A node in the requirements graph.

    Represents a single requirement entity (story, epic, component, etc.).
    """

    id: str = Field(description="Unique node identifier")
    type: NodeType = Field(description="Node type from ontology")
    title: str = Field(description="Human-readable title")
    description: str = Field(default="", description="Detailed description")
    status: NodeStatus = Field(default=NodeStatus.DRAFT, description="Current status")

    # Type-specific attributes stored as flexible dict
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific attributes (e.g., acceptance_criteria, priority)",
    )

    # External tracker reference (populated after sync)
    external_ref: ExternalRef | None = Field(
        default=None,
        description="Reference to external issue tracker",
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="", description="Slack user ID who created")

    # Summarization support
    is_summarized: bool = Field(
        default=False,
        description="True if this node content has been summarized",
    )
    original_description: str = Field(
        default="",
        description="Original description before summarization",
    )

    def to_context_string(self) -> str:
        """
        Convert node to text representation for LLM context.

        Returns:
            Human-readable string describing this node.
        """
        status_emoji = {
            NodeStatus.DRAFT: "[DRAFT]",
            NodeStatus.APPROVED: "[APPROVED]",
            NodeStatus.SYNCED: "[SYNCED]",
            NodeStatus.PARTIALLY_SYNCED: "[PARTIAL]",
            NodeStatus.CONFLICT: "[CONFLICT]",
        }
        parts = [
            f"Node[{self.id}] {self.type.value.upper()}: {self.title}",
            f"  Status: {status_emoji.get(self.status, self.status.value)}",
        ]
        if self.description:
            desc = self.description[:200] + "..." if len(self.description) > 200 else self.description
            parts.append(f"  Description: {desc}")
        if self.attributes:
            for key, value in self.attributes.items():
                parts.append(f"  {key}: {value}")
        if self.external_ref:
            parts.append(f"  External: {self.external_ref.system}:{self.external_ref.id}")
        return "\n".join(parts)


class GraphEdge(BaseModel):
    """
    An edge (relationship) in the requirements graph.

    Represents a directed connection between two nodes.
    """

    source_id: str = Field(description="Source node ID")
    target_id: str = Field(description="Target node ID")
    type: EdgeType = Field(description="Relationship type")
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Edge-specific attributes",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_context_string(self) -> str:
        """
        Convert edge to text representation for LLM context.

        Returns:
            Human-readable string describing this relationship.
        """
        return f"Edge: [{self.source_id}] --{self.type.value}--> [{self.target_id}]"
