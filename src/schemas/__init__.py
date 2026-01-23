"""Core schemas for Jira Analyst Bot."""
from src.schemas.ticket import (
    JiraTicketBase,
    EpicSchema,
    StorySchema,
    TaskSchema,
    BugSchema,
    JiraTicket,
    create_ticket,
)
from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import (
    TicketDraft,
    DraftConstraint,
    ConstraintStatus,
    EvidenceLink,
)
from src.schemas.attribution import (
    MessageAttribution,
    AttributedContent,
)
from src.schemas.conflict import (
    ConflictType,
    ConflictSide,
    DraftConflict,
)

__all__ = [
    # Ticket schemas
    "JiraTicketBase",
    "EpicSchema",
    "StorySchema",
    "TaskSchema",
    "BugSchema",
    "JiraTicket",
    "create_ticket",
    # State schemas
    "AgentState",
    "AgentPhase",
    # Draft schemas
    "TicketDraft",
    "DraftConstraint",
    "ConstraintStatus",
    "EvidenceLink",
    # Attribution schemas (Phase 27.1)
    "MessageAttribution",
    "AttributedContent",
    # Conflict schemas (Phase 27.3)
    "ConflictType",
    "ConflictSide",
    "DraftConflict",
]
