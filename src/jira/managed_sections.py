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

    If no managed section exists, appends one at the end.
    User-written content is preserved.

    Args:
        description: Current Jira description
        decisions: Decisions to include in managed section

    Returns:
        Updated description with managed section
    """
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
