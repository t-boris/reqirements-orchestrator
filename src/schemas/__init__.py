"""Core schemas for Jira Analyst Bot."""
from src.schemas.approval import (
    ApprovalPolicy,
    ApprovalRequirement,
    ChannelApprovalConfig,
)
from src.schemas.attribution import (
    AttributedContent,
    MessageAttribution,
)
from src.schemas.conflict import (
    ConflictSide,
    ConflictType,
    DraftConflict,
)
from src.schemas.draft import (
    ConstraintStatus,
    DraftConstraint,
    EvidenceLink,
    TicketDraft,
)

# Rebuild TicketDraft to resolve forward reference to MessageAttribution
TicketDraft.model_rebuild()
from src.schemas.state import AgentPhase, AgentState
from src.schemas.structured_draft import (
    DraftChange,
    DraftItem,
    DraftItemStatus,
    DraftKind,
    DraftLifecycle,
    DraftScope,
    StructuredDraft,
)
from src.schemas.ticket import (
    BugSchema,
    EpicSchema,
    JiraTicket,
    JiraTicketBase,
    StorySchema,
    TaskSchema,
    create_ticket,
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
    # Approval schemas (Phase 27.4)
    "ApprovalPolicy",
    "ApprovalRequirement",
    "ChannelApprovalConfig",
    # Structured Draft schemas (Phase 28)
    "StructuredDraft",
    "DraftKind",
    "DraftScope",
    "DraftLifecycle",
    "DraftItem",
    "DraftItemStatus",
    "DraftChange",
]
