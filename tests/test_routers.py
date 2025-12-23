"""Unit tests for graph router functions."""

import pytest

from src.graph.graph import (
    architecture_router,
    conflict_router,
    critique_router,
    discovery_router,
    estimation_router,
    final_review_router,
    human_decision_router,
    impact_router,
    intake_router,
    scope_router,
    security_router,
    should_respond_router,
    story_router,
    task_router,
    validation_router,
)
from src.graph.state import HumanDecision, IntentType, WorkflowPhase


class TestShouldRespondRouter:
    """Tests for should_respond_router."""

    def test_should_respond_true(self):
        state = {"should_respond": True}
        assert should_respond_router(state) == "process"

    def test_should_respond_false(self):
        state = {"should_respond": False}
        assert should_respond_router(state) == "silent"

    def test_should_respond_missing(self):
        state = {}
        assert should_respond_router(state) == "silent"


class TestIntakeRouter:
    """Tests for intake_router."""

    def test_no_response(self):
        state = {"should_respond": False}
        assert intake_router(state) == "no_response"

    def test_jira_sync(self):
        state = {"should_respond": True, "intent": IntentType.JIRA_SYNC.value}
        assert intake_router(state) == "jira_write"

    def test_jira_read(self):
        state = {"should_respond": True, "intent": IntentType.JIRA_READ.value}
        assert intake_router(state) == "jira_read"

    def test_jira_status(self):
        state = {"should_respond": True, "intent": IntentType.JIRA_STATUS.value}
        assert intake_router(state) == "jira_status"

    def test_jira_add(self):
        state = {"should_respond": True, "intent": IntentType.JIRA_ADD.value}
        assert intake_router(state) == "jira_add"

    def test_jira_update(self):
        state = {"should_respond": True, "intent": IntentType.JIRA_UPDATE.value}
        assert intake_router(state) == "jira_update"

    def test_jira_delete(self):
        state = {"should_respond": True, "intent": IntentType.JIRA_DELETE.value}
        assert intake_router(state) == "jira_delete"

    def test_modification_triggers_impact_analysis(self):
        state = {"should_respond": True, "intent": IntentType.MODIFICATION.value}
        assert intake_router(state) == "impact_analysis"

    def test_question_goes_to_response(self):
        state = {"should_respond": True, "intent": IntentType.QUESTION.value}
        assert intake_router(state) == "response"

    def test_general_goes_to_response(self):
        state = {"should_respond": True, "intent": IntentType.GENERAL.value}
        assert intake_router(state) == "response"

    def test_off_topic_goes_to_response(self):
        state = {"should_respond": True, "intent": IntentType.OFF_TOPIC.value}
        assert intake_router(state) == "response"

    def test_requirement_with_questions_goes_to_discovery(self):
        state = {
            "should_respond": True,
            "intent": IntentType.REQUIREMENT.value,
            "clarifying_questions": ["What is the priority?"],
        }
        assert intake_router(state) == "discovery"

    def test_requirement_without_questions_goes_to_architecture(self):
        state = {
            "should_respond": True,
            "intent": IntentType.REQUIREMENT.value,
            "clarifying_questions": [],
        }
        assert intake_router(state) == "architecture"


class TestDiscoveryRouter:
    """Tests for discovery_router."""

    def test_has_response_and_should_respond(self):
        state = {"response": "What is the scope?", "should_respond": True}
        assert discovery_router(state) == "respond"

    def test_no_response(self):
        state = {"response": None, "should_respond": True}
        assert discovery_router(state) == "draft"

    def test_empty_response(self):
        state = {"response": "", "should_respond": True}
        assert discovery_router(state) == "draft"


class TestArchitectureRouter:
    """Tests for architecture_router."""

    def test_has_response(self):
        state = {"response": "Option 1, Option 2", "should_respond": True}
        assert architecture_router(state) == "respond"

    def test_architecture_chosen(self):
        state = {"response": None, "chosen_architecture": "microservices"}
        assert architecture_router(state) == "scope"

    def test_default_respond(self):
        state = {}
        assert architecture_router(state) == "respond"


class TestScopeRouter:
    """Tests for scope_router."""

    def test_has_response(self):
        state = {"response": "Scope defined", "should_respond": True}
        assert scope_router(state) == "respond"

    def test_epics_defined(self):
        state = {"epics": [{"title": "Epic 1"}]}
        assert scope_router(state) == "stories"

    def test_default_respond(self):
        state = {}
        assert scope_router(state) == "respond"


class TestStoryRouter:
    """Tests for story_router."""

    def test_has_response(self):
        state = {"response": "Stories", "should_respond": True}
        assert story_router(state) == "respond"

    def test_stories_defined(self):
        state = {"stories": [{"title": "Story 1"}]}
        assert story_router(state) == "tasks"

    def test_default_respond(self):
        state = {}
        assert story_router(state) == "respond"


class TestTaskRouter:
    """Tests for task_router."""

    def test_has_response(self):
        state = {"response": "Tasks", "should_respond": True}
        assert task_router(state) == "respond"

    def test_tasks_defined(self):
        state = {"tasks": [{"title": "Task 1"}]}
        assert task_router(state) == "estimation"

    def test_default_respond(self):
        state = {}
        assert task_router(state) == "respond"


class TestEstimationRouter:
    """Tests for estimation_router."""

    def test_has_response(self):
        state = {"response": "Estimation", "should_respond": True}
        assert estimation_router(state) == "respond"

    def test_estimation_done(self):
        state = {"total_story_points": 13}
        assert estimation_router(state) == "security"

    def test_zero_points_still_proceeds(self):
        state = {"total_story_points": 0}
        assert estimation_router(state) == "security"

    def test_default_respond(self):
        state = {}
        assert estimation_router(state) == "respond"


class TestSecurityRouter:
    """Tests for security_router."""

    def test_has_response(self):
        state = {"response": "Security review", "should_respond": True}
        assert security_router(state) == "respond"

    def test_security_phase_proceeds(self):
        state = {"current_phase": WorkflowPhase.SECURITY.value}
        assert security_router(state) == "validation"

    def test_default_respond(self):
        state = {}
        assert security_router(state) == "respond"


class TestValidationRouter:
    """Tests for validation_router."""

    def test_has_response(self):
        state = {"response": "Validation", "should_respond": True}
        assert validation_router(state) == "respond"

    def test_validation_report_exists(self):
        state = {"validation_report": {"passed": True}}
        assert validation_router(state) == "final_review"

    def test_default_respond(self):
        state = {}
        assert validation_router(state) == "respond"


class TestFinalReviewRouter:
    """Tests for final_review_router."""

    def test_always_goes_to_human_approval(self):
        state = {}
        assert final_review_router(state) == "human_approval"


class TestCritiqueRouter:
    """Tests for critique_router."""

    def test_feedback_and_under_limit(self):
        state = {"critique_feedback": ["Needs more detail"], "iteration_count": 1}
        assert critique_router(state) == "refine"

    def test_feedback_at_limit(self):
        state = {"critique_feedback": ["Issue"], "iteration_count": 3}
        # Assuming max_reflexion_iterations is 3
        assert critique_router(state) == "approve"

    def test_no_feedback(self):
        state = {"critique_feedback": [], "iteration_count": 0}
        assert critique_router(state) == "approve"


class TestConflictRouter:
    """Tests for conflict_router."""

    def test_has_conflicts(self):
        state = {"conflicts": [{"type": "duplicate"}]}
        assert conflict_router(state) == "has_conflicts"

    def test_no_conflicts(self):
        state = {"conflicts": []}
        assert conflict_router(state) == "no_conflicts"

    def test_missing_conflicts(self):
        state = {}
        assert conflict_router(state) == "no_conflicts"


class TestHumanDecisionRouter:
    """Tests for human_decision_router."""

    def test_approve(self):
        state = {"human_decision": HumanDecision.APPROVE.value}
        assert human_decision_router(state) == "write_jira"

    def test_approve_always(self):
        state = {"human_decision": HumanDecision.APPROVE_ALWAYS.value}
        assert human_decision_router(state) == "write_jira"

    def test_edit(self):
        state = {"human_decision": HumanDecision.EDIT.value}
        assert human_decision_router(state) == "edit"

    def test_reject(self):
        state = {"human_decision": HumanDecision.REJECT.value}
        assert human_decision_router(state) == "reject"

    def test_pending(self):
        state = {"human_decision": HumanDecision.PENDING.value}
        assert human_decision_router(state) == "pending"

    def test_missing_decision(self):
        state = {}
        assert human_decision_router(state) == "pending"


class TestImpactRouter:
    """Tests for impact_router."""

    def test_no_restart_phase(self):
        state = {"restart_phase": None}
        assert impact_router(state) == "response"

    def test_restart_from_architecture(self):
        state = {"restart_phase": WorkflowPhase.ARCHITECTURE.value}
        assert impact_router(state) == "architecture"

    def test_restart_from_scope(self):
        state = {"restart_phase": WorkflowPhase.SCOPE.value}
        assert impact_router(state) == "scope"

    def test_restart_from_stories(self):
        state = {"restart_phase": WorkflowPhase.STORIES.value}
        assert impact_router(state) == "stories"

    def test_restart_from_tasks(self):
        state = {"restart_phase": WorkflowPhase.TASKS.value}
        assert impact_router(state) == "tasks"

    def test_restart_from_estimation(self):
        state = {"restart_phase": WorkflowPhase.ESTIMATION.value}
        assert impact_router(state) == "estimation"

    def test_unknown_phase_goes_to_response(self):
        state = {"restart_phase": "unknown_phase"}
        assert impact_router(state) == "response"
