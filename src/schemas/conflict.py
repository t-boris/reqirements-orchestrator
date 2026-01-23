"""Conflict schema for multi-user draft conflicts (Phase 27.3).

Tracks conflicts when multiple users provide contradicting information
in the same draft. Supports explicit resolution with attribution.

Key behaviors:
- Track both sides of a conflict with full attribution
- Support different conflict types (constraint contradiction, value override, etc.)
- Require explicit resolution - never auto-resolve
- Format for Slack display with attribution references
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from uuid import uuid4

from src.schemas.attribution import MessageAttribution


class ConflictType(str, Enum):
    """Types of conflicts in multi-user drafts."""

    CONSTRAINT_CONTRADICTION = "constraint_contradiction"  # Two constraints contradict
    SCOPE_CHANGE = "scope_change"  # User wants to change scope (epic vs stories)
    VALUE_OVERRIDE = "value_override"  # New value replaces existing
    DECISION_REVERSAL = "decision_reversal"  # New statement reverses prior decision


class ConflictSide(BaseModel):
    """One side of a conflict with attribution."""

    content: str = Field(description="The content/statement")
    attribution: MessageAttribution = Field(description="Who said it and when")
    label: str = Field(
        default="",
        description="Short label for button, e.g. 'Keep original'"
    )


class DraftConflict(BaseModel):
    """A detected conflict between two pieces of information.

    Conflicts occur when a new statement contradicts an existing one.
    Both sides are preserved with full attribution until explicitly resolved.
    """

    conflict_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="UUID for this conflict"
    )
    conflict_type: ConflictType = Field(description="Type of conflict")
    field_name: str = Field(description="Which field has the conflict")
    description: str = Field(description="Human-readable conflict description")

    # The two conflicting sides
    existing: ConflictSide = Field(description="The existing/original statement")
    proposed: ConflictSide = Field(description="The new/proposed statement")

    # Resolution state
    resolved: bool = Field(default=False)
    resolution: Optional[str] = Field(
        default=None,
        description="Which side was chosen: 'existing' or 'proposed'"
    )
    resolved_by: Optional[str] = Field(
        default=None,
        description="User ID who resolved"
    )
    resolved_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of resolution"
    )

    def format_for_display(self) -> str:
        """Format conflict for Slack display.

        Returns Slack-formatted markdown showing both sides
        with attribution references.
        """
        existing_ref = self.existing.attribution.format_reference()
        proposed_ref = self.proposed.attribution.format_reference()

        return (
            f"*Conflict detected in {self.field_name}:*\n\n"
            f"> {self.existing.content}\n"
            f"_{existing_ref}_\n\n"
            f"vs.\n\n"
            f"> {self.proposed.content}\n"
            f"_{proposed_ref}_"
        )

    def get_resolution_summary(self) -> str:
        """Get summary of resolution for display.

        Returns empty string if not resolved.
        """
        if not self.resolved:
            return ""

        chosen = self.existing if self.resolution == "existing" else self.proposed
        return f"Resolved: {chosen.content}"
