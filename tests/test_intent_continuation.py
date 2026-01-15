"""Tests for REVIEW_CONTINUATION intent classification.

Phase 15: When user replies to a REVIEW with answers, should classify as
REVIEW_CONTINUATION (not TICKET).
"""
import importlib.util
import os
import sys

import pytest

# Load intent module directly to avoid circular imports through __init__.py
# This is necessary because src.graph.__init__.py imports graph.py which has
# circular dependencies with other modules in the package.
_intent_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'graph', 'intent.py')
_spec = importlib.util.spec_from_file_location("intent", _intent_path)
_intent_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_intent_module)

classify_intent_patterns = _intent_module.classify_intent_patterns
IntentType = _intent_module.IntentType


class TestReviewContinuationPatterns:
    """Test REVIEW_CONTINUATION detection with has_review_context=True."""

    # Key-value format answers
    @pytest.mark.parametrize("message", [
        "Provisioning Type - Automatic",
        "IdP: Okta",
        "Security - Employee loop",
        "Granularity - system access",
    ])
    def test_key_value_answers(self, message):
        """Key-value style answers should be REVIEW_CONTINUATION."""
        result = classify_intent_patterns(message, has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION

    # Multiple comma-separated answers
    @pytest.mark.parametrize("message", [
        "Automatic, Okta, system access, Employee",
        "Option A, standard flow, weekly updates",
    ])
    def test_comma_separated_answers(self, message):
        """Comma-separated answers should be REVIEW_CONTINUATION."""
        result = classify_intent_patterns(message, has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION

    # Numbered answers
    @pytest.mark.parametrize("message", [
        "1. Automatic provisioning",
        "1) Okta for IdP",
        "2. System-level access",
    ])
    def test_numbered_answers(self, message):
        """Numbered answers should be REVIEW_CONTINUATION."""
        result = classify_intent_patterns(message, has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION

    # Bullet answers
    @pytest.mark.parametrize("message", [
        "- Automatic provisioning",
        "• Okta integration",
    ])
    def test_bullet_answers(self, message):
        """Bullet-point answers should be REVIEW_CONTINUATION."""
        result = classify_intent_patterns(message, has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION


class TestReviewContinuationWithoutContext:
    """Without review context, same messages should NOT be REVIEW_CONTINUATION."""

    @pytest.mark.parametrize("message", [
        "Provisioning Type - Automatic",
        "IdP: Okta",
        "1. Automatic provisioning",
    ])
    def test_no_continuation_without_context(self, message):
        """Without has_review_context, should NOT match continuation patterns."""
        result = classify_intent_patterns(message, has_review_context=False)
        # Should either be None (fall to LLM) or different intent
        if result is not None:
            assert result.intent != IntentType.REVIEW_CONTINUATION


class TestNotContinuationPatterns:
    """Test that explicit new requests override continuation detection."""

    @pytest.mark.parametrize("message", [
        "Create a new ticket for this",
        "Let's create a ticket",
        "I need a new task for deployment",
        "Propose a different architecture",
        "Let's start over with a fresh approach",
        "Actually, I want a new feature request",
    ])
    def test_explicit_new_requests_not_continuation(self, message):
        """Explicit new ticket/task requests should NOT be REVIEW_CONTINUATION."""
        result = classify_intent_patterns(message, has_review_context=True)
        # Should either be None (fall to LLM) or be TICKET intent
        if result is not None:
            assert result.intent != IntentType.REVIEW_CONTINUATION


class TestDecisionApprovalStillWorks:
    """Decision approval patterns should still work with review context."""

    @pytest.mark.parametrize("message", [
        "Let's go with this",
        "Approved",
        "Sounds good, let's proceed",
        "Ship it",
    ])
    def test_decision_approval_patterns(self, message):
        """Decision approval patterns should still detect DECISION_APPROVAL."""
        result = classify_intent_patterns(message, has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.DECISION_APPROVAL
