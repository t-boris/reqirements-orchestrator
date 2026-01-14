"""Rich draft schema for PM-machine workflow.

Supports patch-style updates with evidence tracking.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from uuid import uuid4


class ConstraintStatus(str, Enum):
    """Status of a constraint/decision."""
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DEPRECATED = "deprecated"


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
    """
    # Identity
    id: str = Field(default_factory=lambda: str(uuid4()))
    epic_id: Optional[str] = None  # Linked Epic key

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
