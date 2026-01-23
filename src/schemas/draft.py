"""Rich draft schema for PM-machine workflow.

Supports patch-style updates with evidence tracking.
Includes attribution tracking for multi-user support.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from uuid import uuid4

if TYPE_CHECKING:
    from src.schemas.attribution import MessageAttribution


class ConstraintStatus(str, Enum):
    """Status of a constraint/decision."""
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DEPRECATED = "deprecated"


class IssueType(str, Enum):
    """Type of Jira issue to create."""
    EPIC = "epic"
    STORY = "story"
    TASK = "task"
    BUG = "bug"


class RequestedScope(str, Enum):
    """Scope of work items requested by user."""
    EPICS_ONLY = "epics_only"      # User wants only epic-level items
    FULL_PLAN = "full_plan"        # Full breakdown (epics + stories)
    SINGLE_ITEM = "single_item"    # Just one ticket (default)


class DraftConstraint(BaseModel):
    """Structured constraint with status tracking."""
    key: str  # e.g., "API.date_format"
    value: str  # e.g., "unix_timestamp"
    status: ConstraintStatus = ConstraintStatus.PROPOSED
    source_message_ts: Optional[str] = None  # Evidence link


class EvidenceLink(BaseModel):
    """Link to source message for traceability."""
    message_ts: str
    thread_ts: str
    channel_id: str
    text_preview: str = ""  # First ~100 chars
    field_updated: str  # Which draft field this evidence supports


class TicketDraft(BaseModel):
    """Rich draft for ticket creation.

    Supports patch-style updates: each field can be updated independently.
    Evidence links trace every extraction back to source messages.

    Minimum viable for PREVIEW: title + problem + 1 AC
    Type classification: issue_type (Epic/Story/Task/Bug), requested_scope (what to generate)
    """
    # Identity
    id: str = Field(default_factory=lambda: str(uuid4()))
    epic_id: Optional[str] = None  # Linked Epic key

    # Type classification (Phase 26)
    issue_type: Optional[IssueType] = None  # EPIC, STORY, TASK, BUG
    requested_scope: Optional[RequestedScope] = None  # EPICS_ONLY, FULL_PLAN, SINGLE_ITEM

    # Core fields (required for PREVIEW)
    title: str = ""  # Maps to Jira summary
    problem: str = ""  # What problem we're solving

    # Solution fields
    proposed_solution: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)

    # Context fields
    constraints: list[DraftConstraint] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    # Traceability
    evidence_links: list[EvidenceLink] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1  # Increment on each update for race detection

    # Attribution tracking for multi-user support (Phase 27.1)
    attributions: dict[str, "MessageAttribution"] = Field(
        default_factory=dict,
        description="Attribution for each field: {field_name: attribution}"
    )
    # Keys: "title", "problem", "proposed_solution", "constraint_0", "constraint_1", etc.

    def is_empty(self) -> bool:
        """Check if draft has no meaningful content yet."""
        return not (
            self.title.strip()
            or self.problem.strip()
            or self.proposed_solution.strip()
            or self.acceptance_criteria
            or self.constraints
        )

    def get_display_type(self) -> str:
        """Get human-readable issue type for display.

        Returns issue_type value or 'Story' as default.
        """
        if self.issue_type:
            return self.issue_type.value.title()  # "epic" -> "Epic"
        return "Story"  # Default fallback

    def has_content(self) -> bool:
        """Check if draft has any content (opposite of is_empty)."""
        return not self.is_empty()

    def is_preview_ready(self) -> bool:
        """Check if draft has minimum viable content for PREVIEW.

        Minimum: title + problem + at least 1 AC
        """
        return bool(
            self.title.strip()
            and self.problem.strip()
            and len(self.acceptance_criteria) >= 1
        )

    def get_missing_for_preview(self) -> list[str]:
        """Get list of fields needed before PREVIEW."""
        missing = []
        if not self.title.strip():
            missing.append("title")
        if not self.problem.strip():
            missing.append("problem")
        if not self.acceptance_criteria:
            missing.append("acceptance_criteria (at least one)")
        return missing

    def add_evidence(
        self,
        message_ts: str,
        thread_ts: str,
        channel_id: str,
        field_updated: str,
        text_preview: str = "",
    ) -> None:
        """Add evidence link for traceability."""
        self.evidence_links.append(EvidenceLink(
            message_ts=message_ts,
            thread_ts=thread_ts,
            channel_id=channel_id,
            text_preview=text_preview[:100] if text_preview else "",
            field_updated=field_updated,
        ))
        self.updated_at = datetime.utcnow()
        self.version += 1

    def patch(self, **updates) -> "TicketDraft":
        """Apply patch-style updates to draft.

        Only updates provided fields, preserves others.
        Increments version and updates timestamp.
        """
        for key, value in updates.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        self.updated_at = datetime.utcnow()
        self.version += 1
        return self

    def set_with_attribution(
        self,
        field: str,
        value: str,
        author_user_id: str,
        source_message_ts: str,
        source_permalink: Optional[str] = None,
        confidence: float = 1.0,
    ) -> None:
        """Set a field value with attribution tracking.

        Records who set the value and from which message.
        For multi-user support in Phase 27.

        Args:
            field: Field name to set (e.g., "title", "problem")
            value: The value to set
            author_user_id: Slack user ID who provided this content
            source_message_ts: Slack message timestamp as source reference
            source_permalink: Optional permalink to the source message
            confidence: Extraction confidence (0.0-1.0)
        """
        from src.schemas.attribution import MessageAttribution

        if hasattr(self, field):
            setattr(self, field, value)
            self.attributions[field] = MessageAttribution(
                author_user_id=author_user_id,
                source_message_ts=source_message_ts,
                source_permalink=source_permalink,
                confidence=confidence,
            )
            self.updated_at = datetime.utcnow()
            self.version += 1

    def get_attribution(self, field: str) -> Optional["MessageAttribution"]:
        """Get attribution for a field.

        Args:
            field: Field name to get attribution for

        Returns:
            MessageAttribution if field has attribution, None otherwise
        """
        return self.attributions.get(field)

    def get_all_authors(self) -> set[str]:
        """Get all unique author user IDs from attributions.

        Returns:
            Set of Slack user IDs who contributed to this draft
        """
        return {attr.author_user_id for attr in self.attributions.values()}
