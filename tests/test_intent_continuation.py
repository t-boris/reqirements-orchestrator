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


class TestUserDeferringPatterns:
    """Test new patterns added in Phase 17 for user deferring to bot."""

    def test_propose_default(self):
        """'propose default' with review context -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("propose default", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION
        assert "deferring" in result.reasons[0].lower()

    def test_propose_default_how_you_see_it(self):
        """'propose default, how you see it' with review context -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("propose default, how you see it", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION
        assert "deferring" in result.reasons[0].lower()

    def test_you_decide(self):
        """'you decide' with review context -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("you decide for me", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION

    def test_how_you_see_it(self):
        """'how you see it' with review context -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("how do you see it?", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION
        assert "perspective" in result.reasons[0].lower()

    def test_i_like_architecture(self):
        """'I like architecture' with review context -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("I like architecture", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION

    def test_i_like_the_approach(self):
        """'I like the approach' with review context -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("I like the approach", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION

    def test_propose_default_without_context_not_continuation(self):
        """'propose default' WITHOUT review context -> NOT continuation."""
        result = classify_intent_patterns("propose default approach", has_review_context=False)
        # Should be None (fall to LLM) or not REVIEW_CONTINUATION
        if result is not None:
            assert result.intent != IntentType.REVIEW_CONTINUATION

    def test_propose_new_architecture_overrides(self):
        """'propose new architecture' EVEN WITH context -> NOT continuation."""
        result = classify_intent_patterns("propose new architecture", has_review_context=True)
        # Should be None (fall to LLM) because NOT_CONTINUATION overrides
        assert result is None  # Falls to LLM which will classify as REVIEW

    def test_propose_different_approach_overrides(self):
        """'propose different approach' EVEN WITH context -> NOT continuation."""
        result = classify_intent_patterns("propose different approach", has_review_context=True)
        # Should be None because NOT_CONTINUATION overrides
        assert result is None


class TestBugReproduction:
    """Reproduce exact bugs from production thread (2026-01-15)."""

    def test_bug_1_i_like_architecture(self):
        """Bug #1: 'I like architecture' after review -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("I like architecture", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION, \
            "Bug #1: Should recognize positive response as continuation"

    def test_bug_3_propose_default(self):
        """Bug #3: 'propose default, how you see it' -> REVIEW_CONTINUATION."""
        result = classify_intent_patterns("propose default, how you see it", has_review_context=True)
        assert result is not None
        assert result.intent == IntentType.REVIEW_CONTINUATION, \
            "Bug #3: Should not start new REVIEW when user asks bot to decide"
