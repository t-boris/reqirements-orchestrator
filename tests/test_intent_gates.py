"""Tests for Stage 0 intent pre-gates."""
import pytest
from src.graph.intent_gates import (
    run_pre_gates,
    check_terminal_intent,
    check_draft_priority,
    check_risk_guard,
    GateResult,
    PreGateOutput,
)


class TestTerminalIntent:
    """Test terminal intent detection."""

    def test_help_command_bypasses(self):
        result = check_terminal_intent("help", is_command=True, command_name="help")
        assert result is not None
        assert result.result == GateResult.BYPASS
        assert result.bypass_intent == "meta"

    def test_sync_command_bypasses(self):
        result = check_terminal_intent("sync", is_command=True, command_name="sync")
        assert result is not None
        assert result.result == GateResult.BYPASS
        assert result.bypass_intent == "sync_request"

    def test_regular_message_passes(self):
        result = check_terminal_intent("hello", is_command=False, command_name=None)
        assert result is None  # No bypass


class TestDraftPriority:
    """Test draft priority constraint."""

    def test_active_draft_constrains(self):
        # Mock state with draft
        class MockDraft:
            title = "Test Draft"

        state = {"draft": MockDraft()}
        result = check_draft_priority(state, thread_ts="123.456")

        assert result is not None
        assert result.result == GateResult.CONSTRAIN
        assert "build" in result.priority_modes

    def test_no_draft_passes(self):
        state = {"draft": None}
        result = check_draft_priority(state, thread_ts="123.456")
        assert result is None


class TestRiskGuard:
    """Test risk guard for low-confidence writes."""

    def test_low_margin_guards(self):
        result = check_risk_guard(
            proposed_intent="jira_command",
            proposed_risk="write",
            confidence=0.8,
            margin=0.1,  # Below 0.15 threshold
        )
        assert result is not None
        assert result.result == GateResult.GUARD

    def test_safe_operations_pass(self):
        result = check_risk_guard(
            proposed_intent="review",
            proposed_risk="safe",
            confidence=0.6,
            margin=0.1,
        )
        assert result is None  # No guard for safe ops

    def test_high_confidence_passes(self):
        result = check_risk_guard(
            proposed_intent="jira_command",
            proposed_risk="write",
            confidence=0.9,
            margin=0.3,
        )
        assert result is None  # High margin, passes
