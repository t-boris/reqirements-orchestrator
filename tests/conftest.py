"""
Pytest configuration and shared fixtures.
"""

import pytest
from typing import AsyncGenerator

from src.core.events.store import EventStore
from src.core.services.graph_service import GraphService
from src.core.graph.graph import RequirementsGraph
from src.core.graph.models import NodeType, EdgeType


@pytest.fixture
def event_store() -> EventStore:
    """Create a fresh event store for testing."""
    return EventStore()


@pytest.fixture
def graph_service(event_store: EventStore) -> GraphService:
    """Create a graph service for testing."""
    return GraphService(event_store)


@pytest.fixture
def sample_graph() -> RequirementsGraph:
    """Create a sample graph with test data."""
    from src.core.graph.models import GraphNode, GraphEdge

    graph = RequirementsGraph(channel_id="test-channel")

    # Add nodes
    goal = GraphNode(
        id="goal-1",
        type=NodeType.GOAL,
        title="Build a user authentication system",
        description="Complete authentication flow",
    )
    epic = GraphNode(
        id="epic-1",
        type=NodeType.EPIC,
        title="User Login",
        description="Allow users to log in",
    )
    story = GraphNode(
        id="story-1",
        type=NodeType.STORY,
        title="Login form",
        description="As a user, I want to log in with email/password",
        attributes={
            "actor": "User",
            "acceptance_criteria": [
                "Form has email and password fields",
                "Shows error on invalid credentials",
            ],
        },
    )
    component = GraphNode(
        id="comp-1",
        type=NodeType.COMPONENT,
        title="Auth Service",
        description="Authentication microservice",
    )

    graph.add_node(goal)
    graph.add_node(epic)
    graph.add_node(story)
    graph.add_node(component)

    # Add edges
    graph.add_edge(GraphEdge(
        source_id="goal-1",
        target_id="epic-1",
        type=EdgeType.DECOMPOSES_TO,
    ))
    graph.add_edge(GraphEdge(
        source_id="epic-1",
        target_id="story-1",
        type=EdgeType.DECOMPOSES_TO,
    ))
    graph.add_edge(GraphEdge(
        source_id="story-1",
        target_id="comp-1",
        type=EdgeType.REQUIRES_COMPONENT,
    ))

    return graph


@pytest.fixture
def test_channel_id() -> str:
    """Standard test channel ID."""
    return "C12345678"


@pytest.fixture
def test_user_id() -> str:
    """Standard test user ID."""
    return "U12345678"
