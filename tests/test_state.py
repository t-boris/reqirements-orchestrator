"""Unit tests for state schema and utilities."""

import pytest

from src.graph.state import (
    HumanDecision,
    IntentType,
    ProgressStepStatus,
    RequirementState,
    WorkflowPhase,
    create_initial_state,
)


class TestIntentType:
    """Tests for IntentType enum."""

    def test_requirement_value(self):
        assert IntentType.REQUIREMENT.value == "requirement"

    def test_modification_value(self):
        assert IntentType.MODIFICATION.value == "modification"

    def test_jira_crud_intents(self):
        """All Jira CRUD intents should be defined."""
        assert IntentType.JIRA_SYNC.value == "jira_sync"
        assert IntentType.JIRA_READ.value == "jira_read"
        assert IntentType.JIRA_STATUS.value == "jira_status"
        assert IntentType.JIRA_ADD.value == "jira_add"
        assert IntentType.JIRA_UPDATE.value == "jira_update"
        assert IntentType.JIRA_DELETE.value == "jira_delete"

    def test_all_intents_unique(self):
        """All intent values should be unique."""
        values = [intent.value for intent in IntentType]
        assert len(values) == len(set(values))


class TestHumanDecision:
    """Tests for HumanDecision enum."""

    def test_all_decisions(self):
        assert HumanDecision.APPROVE.value == "approve"
        assert HumanDecision.APPROVE_ALWAYS.value == "approve_always"
        assert HumanDecision.EDIT.value == "edit"
        assert HumanDecision.REJECT.value == "reject"
        assert HumanDecision.PENDING.value == "pending"


class TestWorkflowPhase:
    """Tests for WorkflowPhase enum."""

    def test_phase_order(self):
        """Phases should follow logical order."""
        phases = [
            WorkflowPhase.INTAKE,
            WorkflowPhase.DISCOVERY,
            WorkflowPhase.ARCHITECTURE,
            WorkflowPhase.SCOPE,
            WorkflowPhase.STORIES,
            WorkflowPhase.TASKS,
            WorkflowPhase.ESTIMATION,
            WorkflowPhase.SECURITY,
            WorkflowPhase.VALIDATION,
            WorkflowPhase.REVIEW,
            WorkflowPhase.JIRA_SYNC,
            WorkflowPhase.MONITORING,
            WorkflowPhase.COMPLETE,
        ]
        assert len(phases) == len(WorkflowPhase)


class TestProgressStepStatus:
    """Tests for ProgressStepStatus enum."""

    def test_all_statuses(self):
        assert ProgressStepStatus.PENDING.value == "pending"
        assert ProgressStepStatus.IN_PROGRESS.value == "in_progress"
        assert ProgressStepStatus.COMPLETE.value == "complete"
        assert ProgressStepStatus.SKIPPED.value == "skipped"
        assert ProgressStepStatus.WAITING_USER.value == "waiting_user"


class TestCreateInitialState:
    """Tests for create_initial_state function."""

    def test_minimal_state(self):
        """Create state with minimal required fields."""
        state = create_initial_state(
            channel_id="C123",
            user_id="U456",
            message="Hello",
        )

        assert state["channel_id"] == "C123"
        assert state["user_id"] == "U456"
        assert state["message"] == "Hello"
        assert state["thread_ts"] is None
        assert state["is_mention"] is False
        assert state["attachments"] == []

    def test_full_state(self):
        """Create state with all fields."""
        state = create_initial_state(
            channel_id="C123",
            user_id="U456",
            message="Build a feature",
            thread_ts="1234567890.123456",
            attachments=[{"type": "file", "content": "spec.md"}],
            is_mention=True,
            channel_config={"jira_project_key": "TEST"},
        )

        assert state["thread_ts"] == "1234567890.123456"
        assert state["is_mention"] is True
        assert len(state["attachments"]) == 1
        assert state["channel_config"]["jira_project_key"] == "TEST"

    def test_default_values(self):
        """All default values should be set correctly."""
        state = create_initial_state(
            channel_id="C123",
            user_id="U456",
            message="Test",
        )

        # Conversation
        assert state["messages"] == []

        # Memory
        assert state["zep_facts"] == []
        assert state["zep_session_id"] is None
        assert state["related_jira_issues"] == []

        # Intent
        assert state["intent"] is None
        assert state["intent_confidence"] == 0.0
        assert state["persona_matches"] == []
        assert state["active_persona"] is None

        # Processing
        assert state["current_goal"] is None
        assert state["draft"] is None
        assert state["all_drafts"] is None
        assert state["is_complex_requirement"] is False
        assert state["critique_feedback"] == []
        assert state["iteration_count"] == 0
        assert state["conflicts"] == []

        # HITL
        assert state["awaiting_human"] is False
        assert state["human_decision"] == HumanDecision.PENDING.value
        assert state["human_feedback"] is None

        # Jira
        assert state["jira_action"] is None
        assert state["jira_issue_key"] is None
        assert state["jira_issue_data"] is None

        # Output
        assert state["response"] is None
        assert state["should_respond"] is False
        assert state["error"] is None

        # Workflow Progress
        assert state["current_phase"] is None
        assert state["phase_history"] == []
        assert state["progress_steps"] == []

        # Impact Analysis
        assert state["impact_level"] is None
        assert state["impact_confidence"] is None
        assert state["affected_items"] == []
        assert state["cascade_phases"] == []
        assert state["restart_phase"] is None

    def test_jira_command_state(self):
        """Jira command state fields should be initialized."""
        state = create_initial_state(
            channel_id="C123",
            user_id="U456",
            message="Test",
        )

        assert state["jira_command_target"] is None
        assert state["jira_command_parent"] is None
        assert state["jira_command_type"] is None
        assert state["jira_command_updates"] is None

    def test_hierarchy_state(self):
        """Hierarchy fields should be initialized."""
        state = create_initial_state(
            channel_id="C123",
            user_id="U456",
            message="Test",
        )

        assert state["epics"] == []
        assert state["stories"] == []
        assert state["tasks"] == []
