"""Tests for event validation logic."""
import importlib.util
import os

import pytest

# Load modules directly to avoid circular imports through __init__.py
# This pattern is used across the test suite due to circular dependencies
# in src.graph.__init__.py

# Load state module for WorkflowStep enum
_state_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'schemas', 'state.py')
_spec = importlib.util.spec_from_file_location("state", _state_path)
_state_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_state_module)

WorkflowStep = _state_module.WorkflowStep

# Load event_validation module
_ev_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'graph', 'event_validation.py')
_spec = importlib.util.spec_from_file_location("event_validation", _ev_path)
_ev_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ev_module)

validate_event = _ev_module.validate_event
validate_ui_version = _ev_module.validate_ui_version
ALLOWED_EVENTS = _ev_module.ALLOWED_EVENTS


class TestValidateEvent:
    """Tests for validate_event function."""

    def test_approve_allowed_in_draft_preview(self):
        """Approve button works in draft preview."""
        assert validate_event(WorkflowStep.DRAFT_PREVIEW, "approve") is True

    def test_edit_allowed_in_draft_preview(self):
        """Edit button works in draft preview."""
        assert validate_event(WorkflowStep.DRAFT_PREVIEW, "edit") is True

    def test_approve_not_allowed_in_scope_gate(self):
        """Approve button not allowed in scope gate (stale)."""
        assert validate_event(WorkflowStep.SCOPE_GATE, "approve") is False

    def test_no_events_allowed_in_frozen_review(self):
        """Frozen review has no allowed actions."""
        assert validate_event(WorkflowStep.REVIEW_FROZEN, "approve") is False
        assert validate_event(WorkflowStep.REVIEW_FROZEN, "edit") is False

    def test_none_step_rejects_all(self):
        """No workflow step = all events rejected."""
        assert validate_event(None, "approve") is False

    def test_scope_gate_actions(self):
        """Scope gate allows its specific actions."""
        assert validate_event(WorkflowStep.SCOPE_GATE, "select_review") is True
        assert validate_event(WorkflowStep.SCOPE_GATE, "select_ticket") is True
        assert validate_event(WorkflowStep.SCOPE_GATE, "dismiss") is True


class TestValidateUiVersion:
    """Tests for UI version validation."""

    def test_matching_version_passes(self):
        """Same version = valid."""
        assert validate_ui_version(5, 5) is True

    def test_old_version_fails(self):
        """Old button version = stale."""
        assert validate_ui_version(6, 5) is False

    def test_future_version_fails(self):
        """Future version (shouldn't happen) = also stale."""
        assert validate_ui_version(5, 6) is False


class TestAllowedEventsComplete:
    """Verify ALLOWED_EVENTS covers all WorkflowStep values."""

    def test_all_steps_have_allowed_events(self):
        """Every WorkflowStep must be in ALLOWED_EVENTS."""
        for step in WorkflowStep:
            assert step in ALLOWED_EVENTS, f"Missing ALLOWED_EVENTS for {step}"
