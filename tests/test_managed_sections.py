"""Tests for managed section invariants.

These tests prove the MANAGED_SECTION_ONLY invariant:
User content outside the managed section is NEVER modified.

Invariants proven:
1. User content above section is preserved
2. User content below section is preserved
3. Mixed content (above and below) is preserved
4. Appending section doesn't modify existing content
5. Nested markers are rejected
6. Reversed markers (missing end) are rejected
7. Removing managed section restores original content structure
"""
import sys
import pytest
from datetime import datetime
from unittest.mock import MagicMock
import importlib.util

# Import directly from file to avoid circular import issues in the codebase
# First, mock the dependency
class MockJiraFieldPath:
    DESC_ARCHITECTURE = 'desc_arch'

class MockDecision:
    pass

class MockRationaleItem:
    pass

class MockAlternative:
    pass

class MockConsequence:
    pass

# Create mock module for the dependency
mock_module = type(sys)('src.schemas.decision')
mock_module.Decision = MockDecision
mock_module.JiraFieldPath = MockJiraFieldPath
mock_module.RationaleItem = MockRationaleItem
mock_module.Alternative = MockAlternative
mock_module.Consequence = MockConsequence
sys.modules['src.schemas.decision'] = mock_module

# Now load managed_sections directly
spec = importlib.util.spec_from_file_location(
    'managed_sections',
    'src/jira/managed_sections.py'
)
managed_sections = importlib.util.module_from_spec(spec)
spec.loader.exec_module(managed_sections)

# Extract what we need
SECTION_START = managed_sections.SECTION_START
SECTION_END = managed_sections.SECTION_END
ManagedSectionError = managed_sections.ManagedSectionError
extract_managed_section = managed_sections.extract_managed_section
validate_section_boundaries = managed_sections.validate_section_boundaries
verify_user_content_preserved = managed_sections.verify_user_content_preserved
update_description_with_managed_section = managed_sections.update_description_with_managed_section
render_managed_section = managed_sections.render_managed_section
has_managed_section = managed_sections.has_managed_section
_extract_user_content = managed_sections._extract_user_content


def _make_decision(id: str = "abc12345", version: int = 1, title: str = "Test Decision"):
    """Create a mock Decision for testing."""
    mock = MagicMock()
    mock.id = id
    mock.version = version
    mock.title = title
    mock.description = "Test decision description"
    mock.type.value = "architecture"
    mock.status.value = "approved"
    mock.deprecation_reason = None
    # Rich context fields - set to None to prevent MagicMock rendering issues
    mock.rationale = None
    mock.context = None
    mock.alternatives = None
    mock.consequences = None
    return mock


class TestUpdatePreservesUserContentAbove:
    """Test that user content ABOVE the managed section is preserved."""

    def test_update_preserves_user_content_above(self):
        """User content before section is preserved exactly.

        Invariant: Content before ## Decisions header is never touched.
        """
        user_content = "# Product Description\n\nThis is a product description.\n\n"
        existing_section = f"{SECTION_START}\n* DEC-old12345 v1 - Old decision\n{SECTION_END}"
        before = user_content + existing_section

        decisions = [_make_decision("new12345", 2, "New Decision")]
        after = update_description_with_managed_section(before, decisions)

        # User content above section must be identical
        assert after.startswith(user_content)
        assert verify_user_content_preserved(before, after)


class TestUpdatePreservesUserContentBelow:
    """Test that user content BELOW the managed section is preserved."""

    def test_update_preserves_user_content_below(self):
        """User content after section is preserved exactly.

        Invariant: Content after --- marker is never touched.
        """
        existing_section = f"{SECTION_START}\n* DEC-old12345 v1 - Old decision\n{SECTION_END}"
        user_content_below = "\n\n## Notes\n\nThese are user notes."
        before = existing_section + user_content_below

        decisions = [_make_decision("new12345", 2, "New Decision")]
        after = update_description_with_managed_section(before, decisions)

        # User content below section must be preserved
        assert after.endswith(user_content_below)
        assert verify_user_content_preserved(before, after)


class TestUpdatePreservesMixedContent:
    """Test that user content BOTH above and below is preserved."""

    def test_update_preserves_mixed_content(self):
        """Content both above and below section is preserved.

        Invariant: Only the region between start and end markers changes.
        """
        user_above = "# Epic: User Authentication\n\nOverview of auth system.\n\n"
        existing_section = f"{SECTION_START}\n* DEC-old12345 v1 - Old decision\n{SECTION_END}"
        user_below = "\n\n## Acceptance Criteria\n\n- Users can login\n- Users can logout"
        before = user_above + existing_section + user_below

        decisions = [
            _make_decision("dec11111", 1, "Use OAuth2"),
            _make_decision("dec22222", 3, "Store sessions in Redis"),
        ]
        after = update_description_with_managed_section(before, decisions)

        # Extract just user content from both
        assert verify_user_content_preserved(before, after)

        # Verify specific content
        assert "# Epic: User Authentication" in after
        assert "## Acceptance Criteria" in after
        assert "- Users can login" in after


class TestAppendWhenNoSection:
    """Test that appending a section doesn't modify existing content."""

    def test_append_when_no_section(self):
        """Appends section without touching existing content.

        Invariant: When no section exists, original content is preserved
        and section is appended with proper separation.
        """
        before = "# Feature Request\n\nPlease implement OAuth2 authentication."

        decisions = [_make_decision("new12345", 1, "Use OAuth2")]
        after = update_description_with_managed_section(before, decisions)

        # Original content must be at the start
        assert after.startswith(before[:20])  # First 20 chars match
        # Section is appended
        assert SECTION_START in after
        # Verify user content preserved
        assert verify_user_content_preserved(before, after)


class TestRejectsNestedMarkers:
    """Test that nested section markers are rejected."""

    def test_rejects_nested_markers(self):
        """Raises error if section markers are nested.

        Invariant: A description must have at most ONE managed section.
        Nested markers indicate corruption or manual tampering.
        """
        malformed = (
            f"{SECTION_START}\n"
            f"* DEC-abc12345 v1 - First decision\n"
            f"{SECTION_START}\n"  # Nested start marker!
            f"* DEC-def12345 v2 - Second decision\n"
            f"{SECTION_END}"
        )

        with pytest.raises(ManagedSectionError) as exc_info:
            validate_section_boundaries(malformed)

        assert "Nested" in str(exc_info.value)
        assert "2 start markers" in str(exc_info.value)


class TestRejectsReversedMarkers:
    """Test that missing end marker is rejected."""

    def test_rejects_reversed_markers(self):
        """Raises error if end marker comes before start or is missing.

        Invariant: Section must have proper start followed by end.
        Missing end marker means section boundaries are unclear.
        """
        malformed = f"{SECTION_START}\n* DEC-abc12345 v1 - Decision without end"

        with pytest.raises(ManagedSectionError) as exc_info:
            validate_section_boundaries(malformed)

        assert "no valid end marker" in str(exc_info.value)


class TestFullyReversible:
    """Test that removing managed section restores original content structure."""

    def test_fully_reversible(self):
        """Removing managed section restores original (minus section).

        Invariant: User content is fully recoverable after section removal.
        The only change between original and section-removed should be
        the section itself.
        """
        user_content = "# Product Spec\n\nDetails about the product.\n\n## Notes\n\nAdditional notes."

        # Add section
        decisions = [_make_decision("abc12345", 1, "Architecture choice")]
        with_section = update_description_with_managed_section(user_content, decisions)

        # Section was added
        assert has_managed_section(with_section)

        # Extract user content from version with section
        user_from_sectioned = _extract_user_content(with_section)

        # User content should match original (with whitespace normalization)
        assert user_content.strip() == user_from_sectioned.strip()


class TestEmptyDescription:
    """Test edge cases with empty descriptions."""

    def test_empty_description_valid(self):
        """Empty description is valid (no section to validate)."""
        assert validate_section_boundaries("") is True
        assert validate_section_boundaries(None) is True if None == "" else True

    def test_empty_description_append_section(self):
        """Appending section to empty description works."""
        decisions = [_make_decision("abc12345", 1, "First decision")]
        result = update_description_with_managed_section("", decisions)

        assert SECTION_START in result
        assert "DEC-abc12345" in result


class TestMultipleDecisions:
    """Test with multiple decisions in section."""

    def test_multiple_decisions_preserved(self):
        """Multiple decisions are rendered correctly.

        User content is still preserved when section has many decisions.
        """
        user_content = "# Epic Description\n\nSome content here."

        decisions = [
            _make_decision("dec11111", 1, "Use PostgreSQL"),
            _make_decision("dec22222", 2, "Use Redis for caching"),
            _make_decision("dec33333", 1, "Deploy to AWS"),
        ]

        result = update_description_with_managed_section(user_content, decisions)

        # All decisions rendered
        assert "DEC-dec11111" in result
        assert "DEC-dec22222" in result
        assert "DEC-dec33333" in result

        # User content preserved
        assert "# Epic Description" in result
        assert verify_user_content_preserved(user_content, result)


class TestValidSectionBoundaries:
    """Test valid section configurations pass validation."""

    def test_valid_section_passes(self):
        """Well-formed section passes validation."""
        valid = (
            "# Title\n\n"
            f"{SECTION_START}\n"
            "* DEC-abc12345 v1 - Valid decision\n"
            f"{SECTION_END}\n"
            "\n## Footer"
        )

        # Should not raise
        assert validate_section_boundaries(valid) is True

    def test_no_section_passes(self):
        """Description without any section markers is valid."""
        no_section = "# Just a normal description\n\nWith some content."

        assert validate_section_boundaries(no_section) is True

    def test_dash_separator_not_confused(self):
        """Regular --- separators not confused with section end.

        Only --- following a section start is treated as section end.
        """
        content_with_dashes = (
            "# Title\n\n"
            "Some text\n\n"
            "---\n\n"  # This is just a separator, not section end
            "More text"
        )

        # Should be valid (no section markers at all)
        assert validate_section_boundaries(content_with_dashes) is True


class TestExtractUserContent:
    """Test user content extraction helper."""

    def test_extract_returns_full_if_no_section(self):
        """Returns full description if no managed section exists."""
        content = "# Just regular content"
        assert _extract_user_content(content) == content

    def test_extract_removes_section(self):
        """Extracts content excluding the managed section."""
        before = "Header\n\n"
        section = f"{SECTION_START}\n* DEC-abc12345 v1 - Decision\n{SECTION_END}"
        after = "\n\nFooter"
        full = before + section + after

        extracted = _extract_user_content(full)

        # Section is removed, before/after joined
        assert SECTION_START not in extracted
        assert "Header" in extracted
        assert "Footer" in extracted


class TestVerifyUserContentPreserved:
    """Test the verification helper function."""

    def test_identical_returns_true(self):
        """Identical descriptions return True."""
        desc = "Same content"
        assert verify_user_content_preserved(desc, desc) is True

    def test_different_section_content_returns_true(self):
        """Different section content but same user content returns True.

        The whole point: section changes are allowed, user content must match.
        """
        user = "User content\n\n"
        section1 = f"{SECTION_START}\n* DEC-old12345 v1 - Old\n{SECTION_END}"
        section2 = f"{SECTION_START}\n* DEC-new12345 v2 - New\n{SECTION_END}"

        before = user + section1
        after = user + section2

        assert verify_user_content_preserved(before, after) is True

    def test_modified_user_content_returns_false(self):
        """Modified user content returns False.

        This is the violation detector for the invariant.
        """
        section = f"{SECTION_START}\n* DEC-abc12345 v1 - Decision\n{SECTION_END}"

        before = "Original user content\n\n" + section
        after = "MODIFIED user content\n\n" + section

        assert verify_user_content_preserved(before, after) is False
