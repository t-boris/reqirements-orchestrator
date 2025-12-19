"""
Integration tests for the full MARO workflow.
"""

import pytest
from src.core.events.store import EventStore
from src.core.services.graph_service import GraphService
from src.core.graph.models import NodeType, NodeStatus, EdgeType


class TestFullWorkflow:
    """Integration tests for complete workflows."""

    @pytest.fixture
    def setup_services(self):
        """Set up services for testing."""
        event_store = EventStore()
        graph_service = GraphService(event_store)
        return event_store, graph_service

    def test_requirements_gathering_workflow(self, setup_services):
        """Test a complete requirements gathering workflow."""
        event_store, graph_service = setup_services
        channel = "test-channel"
        user = "user-1"

        # 1. Create a goal
        goal = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.GOAL,
            title="Build user authentication",
            description="Allow users to securely access the application",
        )

        # 2. Decompose into epics
        epic = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.EPIC,
            title="User Login",
            description="Implement login functionality",
        )
        graph_service.add_edge(
            channel_id=channel,
            user_id=user,
            source_id=goal.id,
            target_id=epic.id,
            edge_type=EdgeType.DECOMPOSES_TO,
        )

        # 3. Create stories
        story = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.STORY,
            title="Login form",
            description="As a user, I want to log in with email/password",
            actor="User",
            acceptance_criteria=[
                "Form has email and password fields",
                "Error shown on invalid credentials",
                "Redirects to dashboard on success",
            ],
        )
        graph_service.add_edge(
            channel_id=channel,
            user_id=user,
            source_id=epic.id,
            target_id=story.id,
            edge_type=EdgeType.DECOMPOSES_TO,
        )

        # 4. Add technical component
        component = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.COMPONENT,
            title="Auth Service",
            description="Authentication microservice",
            tech_stack=["Python", "FastAPI", "JWT"],
        )
        graph_service.add_edge(
            channel_id=channel,
            user_id=user,
            source_id=story.id,
            target_id=component.id,
            edge_type=EdgeType.REQUIRES_COMPONENT,
        )

        # 5. Add NFR constraint
        constraint = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.CONSTRAINT,
            title="GDPR Compliance",
            description="Must comply with GDPR regulations",
            type="compliance",
        )
        graph_service.add_edge(
            channel_id=channel,
            user_id=user,
            source_id=story.id,
            target_id=constraint.id,
            edge_type=EdgeType.CONSTRAINED_BY,
        )

        # 6. Validate graph
        issues = graph_service.validate_graph(channel)
        assert len(issues["orphan_nodes"]) == 0  # Story has parent
        assert len(issues["unlinked_stories"]) == 0  # Story has component

        # 7. Approve story
        graph_service.update_node(
            channel_id=channel,
            user_id=user,
            node_id=story.id,
            status=NodeStatus.APPROVED,
        )

        # 8. Check metrics
        state = graph_service.get_graph_state(channel)
        assert state["metrics"]["total_nodes"] == 4
        assert state["metrics"]["total_edges"] == 4
        assert state["metrics"]["completeness_score"] == 100.0

    def test_event_replay_consistency(self, setup_services):
        """Test that replaying events produces consistent state."""
        event_store, graph_service = setup_services
        channel = "test-channel"
        user = "user-1"

        # Perform operations
        node1 = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.EPIC,
            title="Epic 1",
        )
        node2 = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.STORY,
            title="Story 1",
        )
        graph_service.add_edge(
            channel_id=channel,
            user_id=user,
            source_id=node1.id,
            target_id=node2.id,
            edge_type=EdgeType.DECOMPOSES_TO,
        )
        graph_service.update_node(
            channel_id=channel,
            user_id=user,
            node_id=node2.id,
            title="Updated Story",
        )

        # Get current state
        original_state = graph_service.get_graph_state(channel)

        # Create new service and replay
        new_event_store = EventStore()
        new_event_store._events = event_store._events.copy()
        new_event_store._sequences = event_store._sequences.copy()

        replayed_graph = new_event_store.replay(channel)

        # Verify consistency
        assert len(replayed_graph) == original_state["metrics"]["total_nodes"]
        assert replayed_graph.get_node(node2.id).title == "Updated Story"

    def test_conflict_detection(self, setup_services):
        """Test conflict detection between requirements."""
        event_store, graph_service = setup_services
        channel = "test-channel"
        user = "user-1"

        # Create story
        story = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.STORY,
            title="Store passwords in plain text",
        )

        # Create conflicting constraint
        constraint = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.CONSTRAINT,
            title="Security: Must hash passwords",
            type="security",
        )

        # Mark conflict
        graph_service.add_edge(
            channel_id=channel,
            user_id=user,
            source_id=story.id,
            target_id=constraint.id,
            edge_type=EdgeType.CONFLICTS_WITH,
        )

        # Validate
        issues = graph_service.validate_graph(channel)
        assert len(issues["conflicts"]) == 1

    def test_question_blocking(self, setup_services):
        """Test that unanswered questions block stories."""
        event_store, graph_service = setup_services
        channel = "test-channel"
        user = "user-1"

        # Create story
        story = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.STORY,
            title="Implement payment processing",
        )

        # Create blocking question
        question = graph_service.add_node(
            channel_id=channel,
            user_id=user,
            node_type=NodeType.QUESTION,
            title="Which payment gateway to use?",
            answered=False,
        )
        graph_service.add_edge(
            channel_id=channel,
            user_id=user,
            source_id=question.id,
            target_id=story.id,
            edge_type=EdgeType.BLOCKS,
        )

        # Check blocking
        graph = graph_service.get_or_create_graph(channel)
        blocking = graph.find_blocking_questions()
        assert len(blocking) == 1
        assert blocking[0][0].id == question.id
        assert blocking[0][1].id == story.id
