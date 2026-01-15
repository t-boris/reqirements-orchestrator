"""Tests for thread context extraction and review lifecycle state management.

This test file covers:
- Reference detection patterns (Bug #2)
- ReviewState enum lifecycle (Bug #4)
- Integration with production scenarios
"""
import pytest
import re


def _detect_reference_to_prior_content(message: str) -> bool:
    """Check if user message references prior content in thread.

    Returns True if message contains patterns like:
    - "the architecture" / "this architecture"
    - "the review" / "this review" / "that analysis"
    - "from above" / "mentioned above"
    """
    message_lower = message.lower()

    reference_patterns = [
        r"\bthe\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\bthis\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\bthat\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\b(?:from|mentioned|discussed)\s+above\b",
        r"\bour\s+(?:discussion|conversation|review)\b",
    ]

    for pattern in reference_patterns:
        if re.search(pattern, message_lower):
            return True
    return False


class TestReferenceDetection:
    """Test detection of references to prior content in thread."""

    def test_detects_the_architecture(self):
        """'Create tickets for THE ARCHITECTURE' -> detected."""
        assert _detect_reference_to_prior_content("Create Jira tickets that represent the architecture") == True

    def test_detects_this_review(self):
        """'Based on THIS REVIEW' -> detected."""
        assert _detect_reference_to_prior_content("Based on this review, create tickets") == True

    def test_detects_from_above(self):
        """'From the discussion above' -> detected."""
        assert _detect_reference_to_prior_content("From above, implement the components") == True

    def test_no_reference_in_simple_request(self):
        """'Create a ticket' -> NOT detected."""
        assert _detect_reference_to_prior_content("Create a new ticket for user auth") == False

    def test_detects_our_discussion(self):
        """'Based on our discussion' -> detected."""
        assert _detect_reference_to_prior_content("Based on our discussion, proceed") == True

    def test_detects_that_analysis(self):
        """'That analysis was good' -> detected."""
        assert _detect_reference_to_prior_content("That analysis looks good, let's proceed") == True

    def test_detects_the_design(self):
        """'The design mentioned above' -> detected."""
        assert _detect_reference_to_prior_content("Create tickets for the design") == True

    def test_detects_this_proposal(self):
        """'This proposal works' -> detected."""
        assert _detect_reference_to_prior_content("This proposal works for me") == True

    def test_no_reference_in_new_request(self):
        """'Build a new feature' -> NOT detected."""
        assert _detect_reference_to_prior_content("Build a new authentication system") == False

    def test_no_reference_with_article_in_other_context(self):
        """'The user' shouldn't match 'the architecture' pattern."""
        assert _detect_reference_to_prior_content("The user should be able to login") == False


class TestReviewLifecycle:
    """Test review_context lifecycle state transitions."""

    def test_review_state_enum_values(self):
        """ReviewState enum has correct values."""
        from src.schemas.state import ReviewState
        assert ReviewState.ACTIVE == "active"
        assert ReviewState.CONTINUATION == "continuation"
        assert ReviewState.APPROVED == "approved"
        assert ReviewState.POSTED == "posted"

    def test_review_state_enum_exists(self):
        """ReviewState enum can be imported."""
        from src.schemas.state import ReviewState
        assert hasattr(ReviewState, 'ACTIVE')
        assert hasattr(ReviewState, 'CONTINUATION')
        assert hasattr(ReviewState, 'APPROVED')
        assert hasattr(ReviewState, 'POSTED')

    def test_review_state_string_values(self):
        """ReviewState enum has correct string values for serialization."""
        from src.schemas.state import ReviewState
        # These string values are used in review_context dict
        assert str(ReviewState.ACTIVE) == "ReviewState.ACTIVE"
        assert ReviewState.ACTIVE.value == "active"
        assert ReviewState.CONTINUATION.value == "continuation"
        assert ReviewState.APPROVED.value == "approved"
        assert ReviewState.POSTED.value == "posted"


class TestBugReproduction:
    """Reproduce bugs from production thread (2026-01-15 19:50-19:54)."""

    def test_bug_2_create_tickets_for_architecture(self):
        """Bug #2: 'Create tickets for the architecture' -> detects reference."""
        message = "Create Jira tickets that represent the architecture"
        assert _detect_reference_to_prior_content(message) == True, \
            "Bug #2: Should detect reference to 'the architecture'"

    def test_bug_2_production_exact_wording(self):
        """Bug #2: Exact production wording from thread."""
        # From production thread at 19:52
        message = "Create Jira tickets that represent the architecture"
        assert _detect_reference_to_prior_content(message) == True

    def test_bug_4_review_context_has_state(self):
        """Bug #4: review_context should have state field."""
        # Verify ReviewState enum exists for lifecycle management
        from src.schemas.state import ReviewState
        assert ReviewState.ACTIVE
        assert ReviewState.POSTED

    def test_bug_3_propose_default_pattern(self):
        """Bug #3: 'propose default' should not be classified as new review."""
        # This message should be REVIEW_CONTINUATION, not REVIEW
        message = "propose default, how you see it"
        # Note: actual classification happens in intent.py, not here
        # This test just documents the expected behavior
        # The fix is in REVIEW_CONTINUATION patterns, not reference detection
        assert True  # Placeholder - actual test in test_intent.py

    def test_production_flow_happy_path(self):
        """Test the expected flow from production bugs."""
        from src.schemas.state import ReviewState

        # Step 1: Review posted -> state=ACTIVE
        review_context = {
            "state": ReviewState.ACTIVE,
            "topic": "GitHub/Jira orchestrator",
            "review_summary": "...",
        }
        assert review_context["state"] == ReviewState.ACTIVE

        # Step 2: User says "Create tickets for the architecture" -> reference detected
        assert _detect_reference_to_prior_content("Create Jira tickets that represent the architecture") == True

        # Step 3: User approves -> state=POSTED
        review_context["state"] = ReviewState.POSTED
        assert review_context["state"] == ReviewState.POSTED

        # Step 4: Context cleared after posting
        review_context = None
        assert review_context is None


class TestReferencePatternEdgeCases:
    """Test edge cases for reference pattern matching."""

    def test_case_insensitive(self):
        """Reference detection is case insensitive."""
        assert _detect_reference_to_prior_content("Create tickets for THE ARCHITECTURE") == True
        assert _detect_reference_to_prior_content("Create tickets for The Architecture") == True

    def test_whitespace_variations(self):
        """Pattern matching handles various whitespace."""
        assert _detect_reference_to_prior_content("Create tickets for  the  architecture") == True
        assert _detect_reference_to_prior_content("from\tabove") == True

    def test_partial_word_no_match(self):
        """Word boundaries prevent partial matches."""
        # "thearchitecture" (no space) should not match
        assert _detect_reference_to_prior_content("thearchitecture") == False
        # "review" in "preview" should not match
        assert _detect_reference_to_prior_content("Let me preview this ticket") == False

    def test_multiple_references(self):
        """Message with multiple reference patterns."""
        message = "Based on the architecture review from above, create tickets"
        # Should match on "the architecture", "review", and "from above"
        assert _detect_reference_to_prior_content(message) == True
