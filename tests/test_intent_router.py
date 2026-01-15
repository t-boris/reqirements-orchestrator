"""Regression tests for intent classification.

Tests explicit pattern detection and overall classification accuracy.
The pattern matching layer is pure/deterministic and can be tested without mocking.
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


class TestExplicitTicketPatterns:
    """Test explicit TICKET pattern detection."""

    @pytest.mark.parametrize("message", [
        "create a ticket for this feature",
        "draft a ticket for user auth",
        "make a ticket",
        "I need a Jira issue for this",
        "/maro ticket",
        "jira story for notifications",
        "write a ticket for the bug",
        "create ticket please",
        "make a jira ticket for this",
        "jira task for the cleanup",
    ])
    def test_ticket_patterns(self, message):
        """Explicit ticket patterns should be detected."""
        result = classify_intent_patterns(message)
        assert result is not None, f"Expected pattern match for: {message}"
        assert result.intent == IntentType.TICKET
        assert result.confidence == 1.0


class TestExplicitReviewPatterns:
    """Test explicit REVIEW pattern detection."""

    @pytest.mark.parametrize("message", [
        "review this as security",
        "review as architect",
        "analyze the risks",
        "what are the risks here",
        "evaluate this approach",
        "/maro review",
        "don't create a ticket, just review",
        "security review of this feature",
        "architecture review please",
        "propose an architecture for this",
        "identify risks in this design",
        "analyze this from security perspective",
    ])
    def test_review_patterns(self, message):
        """Explicit review patterns should be detected."""
        result = classify_intent_patterns(message)
        assert result is not None, f"Expected pattern match for: {message}"
        assert result.intent == IntentType.REVIEW
        assert result.confidence == 1.0


class TestExplicitDiscussionPatterns:
    """Test explicit DISCUSSION pattern detection."""

    @pytest.mark.parametrize("message", [
        "hi",
        "hello",
        "hey",
        "help",
        "what can you do?",
        "hi!",
        "hello!",
        "hey!",
    ])
    def test_discussion_patterns(self, message):
        """Explicit discussion patterns should be detected."""
        result = classify_intent_patterns(message)
        assert result is not None, f"Expected pattern match for: {message}"
        assert result.intent == IntentType.DISCUSSION
        assert result.confidence == 1.0


class TestNegationPatterns:
    """Test negation patterns override ticket patterns."""

    @pytest.mark.parametrize("message", [
        "don't create a ticket",
        "dont create ticket",
        "no ticket needed",
        "without a ticket",
        "just review this",
    ])
    def test_negation_overrides_ticket(self, message):
        """Negation patterns should route to REVIEW, not TICKET."""
        result = classify_intent_patterns(message)
        assert result is not None, f"Expected pattern match for: {message}"
        assert result.intent == IntentType.REVIEW
        assert result.confidence == 1.0


class TestPersonaHints:
    """Test persona hint extraction from messages."""

    @pytest.mark.parametrize("message,expected_persona", [
        ("review as security", "security"),
        ("review as architect", "architect"),
        ("review as pm", "pm"),
        ("security review of this", "security"),
        ("architecture review please", "architect"),
        ("requirements review", "pm"),
        ("security perspective on this", "security"),
        ("architect perspective please", "architect"),
        ("pm perspective", "pm"),
    ])
    def test_persona_hint(self, message, expected_persona):
        """Persona hints should be extracted correctly."""
        result = classify_intent_patterns(message)
        assert result is not None, f"Expected pattern match for: {message}"
        assert result.persona_hint == expected_persona


class TestConfidenceScores:
    """Test confidence scores for explicit patterns."""

    def test_explicit_pattern_high_confidence(self):
        """Explicit patterns should have confidence 1.0."""
        result = classify_intent_patterns("create a ticket for this")
        assert result is not None
        assert result.confidence == 1.0

    def test_explicit_override_high_confidence(self):
        """Explicit overrides should have confidence 1.0."""
        result = classify_intent_patterns("don't create a ticket")
        assert result is not None
        assert result.confidence == 1.0


class TestAmbiguousMessages:
    """Test that ambiguous messages return None (need LLM)."""

    @pytest.mark.parametrize("message", [
        "we need to add user authentication",
        "the login system is broken",
        "I was thinking about notifications",
        "what do you think about caching?",
        "should we use Redis?",
    ])
    def test_ambiguous_returns_none(self, message):
        """Ambiguous messages should return None (need LLM)."""
        result = classify_intent_patterns(message)
        assert result is None, f"Expected None for ambiguous message: {message}"


class TestPatternMatchReasons:
    """Test that pattern matches include reason strings."""

    def test_ticket_pattern_has_reason(self):
        """Ticket patterns should include reason."""
        result = classify_intent_patterns("create a ticket for this")
        assert result is not None
        assert len(result.reasons) > 0
        assert "pattern:" in result.reasons[0] or "command:" in result.reasons[0]

    def test_review_pattern_has_reason(self):
        """Review patterns should include reason."""
        result = classify_intent_patterns("/maro review")
        assert result is not None
        assert len(result.reasons) > 0
        assert "pattern:" in result.reasons[0] or "command:" in result.reasons[0]
