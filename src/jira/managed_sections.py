"""Managed sections for Jira description updates.

Philosophy: MARO writes only to clearly marked sections.
Hand-written content above/below is never touched.

Format in Jira description:
---
## Decisions (managed by MARO)
* DEC-abc123 v4 - Use ISO 8601 dates
* DEC-def456 v2 - PostgreSQL for persistence
---

Everything outside this block is user-owned.
"""
import re
from dataclasses import dataclass
from typing import Optional

from src.schemas.decision import Decision, JiraFieldPath


class ManagedSectionError(Exception):
    """Raised when managed section operation would violate invariants."""
    pass


# Section markers
SECTION_START = "## Decisions (managed by MARO)"
SECTION_END = "---"  # Horizontal rule marks end
SECTION_PATTERN = re.compile(
    rf"{re.escape(SECTION_START)}\n(.*?)\n{SECTION_END}",
    re.DOTALL
)


@dataclass
class ManagedSection:
    """A managed section within Jira description."""

    field_path: JiraFieldPath
    content: str
    start_pos: int
    end_pos: int


def extract_managed_section(
    description: str,
) -> Optional[ManagedSection]:
    """Extract the managed section from Jira description.

    Returns None if no managed section exists.
    """
    match = SECTION_PATTERN.search(description)
    if not match:
        return None

    return ManagedSection(
        field_path=JiraFieldPath.DESC_ARCHITECTURE,  # Default for decisions
        content=match.group(1).strip(),
        start_pos=match.start(),
        end_pos=match.end(),
    )


def validate_section_boundaries(description: str) -> bool:
    """Validate managed section boundaries are well-formed.

    Checks:
    - If section exists: start marker is followed by end marker (not reversed)
    - No nested section markers
    - Section boundaries are clear

    Args:
        description: Jira description to validate

    Returns:
        True if valid

    Raises:
        ManagedSectionError: If boundaries are malformed
    """
    if not description:
        return True  # Empty description is valid (no section)

    start_positions = [m.start() for m in re.finditer(re.escape(SECTION_START), description)]
    # Find --- that appears after a section start (not arbitrary ---)
    # Only count --- on its own line after SECTION_START
    end_positions = []
    for start_pos in start_positions:
        # Search for --- after this start
        remaining = description[start_pos:]
        # Match newline + --- + (newline or end)
        end_match = re.search(r'\n---(?:\n|$)', remaining)
        if end_match:
            end_positions.append(start_pos + end_match.start() + 1)  # +1 for the newline

    # No markers at all - valid (no section)
    if not start_positions:
        return True

    # Check for multiple start markers (nested)
    if len(start_positions) > 1:
        raise ManagedSectionError(
            f"Nested section markers detected: found {len(start_positions)} start markers"
        )

    # Exactly one start marker - must have matching end
    if len(start_positions) == 1:
        # Use the pattern to find a valid section
        match = SECTION_PATTERN.search(description)
        if not match:
            raise ManagedSectionError(
                "Section start marker found but no valid end marker (---) follows"
            )
        return True

    return True


def _extract_user_content(description: str) -> str:
    """Extract user content (everything outside managed section).

    Args:
        description: Full Jira description

    Returns:
        Content outside the managed section, or full description if no section
    """
    section = extract_managed_section(description)
    if not section:
        return description

    # User content is everything before and after the section
    before = description[:section.start_pos]
    after = description[section.end_pos:]

    return before + after


def verify_user_content_preserved(before: str, after: str) -> bool:
    """Verify user content is identical between two descriptions.

    Use in tests to double-check the MANAGED_SECTION_ONLY invariant.

    Args:
        before: Description before update
        after: Description after update

    Returns:
        True if user content is identical (preserving whitespace normalization)
    """
    before_user = _extract_user_content(before)
    after_user = _extract_user_content(after)

    # Normalize whitespace for comparison (trailing/leading newlines)
    return before_user.strip() == after_user.strip()


def render_managed_section(
    decisions: list[Decision],
) -> str:
    """Render decisions into managed section format.

    Format:
    ## Decisions (managed by MARO)
    * DEC-abc123 v4 - Use ISO 8601 dates
    * DEC-def456 v2 - PostgreSQL for persistence
    ---
    """
    if not decisions:
        return f"{SECTION_START}\n_No decisions linked_\n{SECTION_END}"

    lines = [SECTION_START]
    for decision in decisions:
        lines.append(f"* DEC-{decision.id[:8]} v{decision.version} - {decision.title}")
    lines.append(SECTION_END)

    return "\n".join(lines)


def update_description_with_managed_section(
    description: str,
    decisions: list[Decision],
) -> str:
    """Update Jira description, only modifying the managed section.

    INVARIANT: Only touches content between section markers.
    User content above/below is NEVER modified.

    If no managed section exists, appends one at the end.
    User-written content is preserved.

    Args:
        description: Current Jira description
        decisions: Decisions to include in managed section

    Returns:
        Updated description with managed section

    Raises:
        ManagedSectionError: If section boundaries are malformed
    """
    # Validate section boundaries before modifying
    validate_section_boundaries(description)

    new_section = render_managed_section(decisions)

    existing = extract_managed_section(description)
    if existing:
        # Replace existing section
        return (
            description[:existing.start_pos] +
            new_section +
            description[existing.end_pos:]
        )
    else:
        # Append to end (with blank line separator)
        separator = "\n\n" if description.strip() else ""
        return description + separator + new_section


def has_managed_section(description: str) -> bool:
    """Check if description contains a managed section."""
    return SECTION_START in description
