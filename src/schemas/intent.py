"""Intent types and related schemas.

Defines the intent classification types and subtypes used throughout the system.
"""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OpsSubtype(str, Enum):
    """Subtypes for OPS intent."""
    DEBUG = "debug"      # Triage failures, retry
    EXPLAIN = "explain"  # Policy trace, show reasoning


class SuperMode(str, Enum):
    """User-facing super-modes (5 modes for simplicity).

    Users should think in 5 modes, not 13 intents.
    This is presentation layer only — internal routing still uses fine-grained intents.
    """
    BUILD = "build"        # "I'm building something"
    OPERATE = "operate"    # "I'm managing Jira"
    DECIDE = "decide"      # "I'm recording a decision"
    THINK = "think"        # "Help me think"
    CHAT = "chat"          # "Just talking"


class Intent(str, Enum):
    """Intent classification types.

    Primary intents represent what the user wants to accomplish.
    """
    # Primary intents
    WORKITEM_CREATE = "workitem_create"  # Create new work item
    DRAFT_REFINE = "draft_refine"        # Refine/clarify current draft (Phase 26) - ASKING about structure
    DRAFT_TRANSFORM = "draft_transform"  # Transform draft structure (Phase 28) - COMMANDING structure change
    TICKET_ACTION = "ticket_action"      # Actions on existing ticket
    JIRA_COMMAND = "jira_command"        # Modify ticket fields
    SYNC_REQUEST = "sync_request"        # Bulk sync
    JIRA_SEARCH = "jira_search"          # Search existing
    REVIEW = "review"                    # Analysis/feedback
    DISCUSSION = "discussion"            # Greeting/casual
    META = "meta"                        # Questions about bot
    AMBIGUOUS = "ambiguous"              # Unclear intent
    CHANGE_REQUEST = "change_request"    # Diff-based updates (Phase 25.3)
    OPS = "ops"                          # Operational mode (debug/explain)
    DECISION = "decision"                # User stating a decision to record (Phase 30)

    # Deprecated aliases
    TICKET = "ticket"  # @deprecated: Use WORKITEM_CREATE

    @classmethod
    def normalize(cls, intent: "Intent") -> "Intent":
        """Normalize deprecated intents to their current equivalents."""
        if intent == cls.TICKET:
            return cls.WORKITEM_CREATE
        return intent


class IntentResult(BaseModel):
    """Result of intent classification."""
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    persona_hint: Optional[Literal["pm", "architect", "security"]] = None
    topic: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)
    # For TICKET_ACTION intent
    ticket_key: Optional[str] = None  # e.g., "SCRUM-113"
    action_type: Optional[Literal["create_subtask", "create_stories", "update", "add_comment", "link"]] = None
    # For JIRA_COMMAND intent
    command_type: Optional[Literal["update", "delete"]] = None  # Type of Jira command
    command_field: Optional[str] = None  # Field to change (priority, status, assignee, etc.)
    command_value: Optional[str] = None  # New value for the field
    target_type: Optional[Literal["explicit", "contextual"]] = None  # How target was specified
    # For JIRA_SEARCH intent
    search_query: Optional[str] = None  # What to search for in Jira
    # For OPS intent
    ops_subtype: Optional[OpsSubtype] = None
    # For CHANGE_REQUEST intent
    change_targets: list[str] = Field(default_factory=list)  # Target keys/ids to change
    change_operation: Optional[Literal["update", "delete", "split", "merge", "move", "link"]] = None
    # Context relation (Phase 26) - how message relates to active context
    context_relation: Optional[Literal["continue", "refine", "change", "new_topic"]] = None
    # For DRAFT_TRANSFORM intent (Phase 28) - structural mutation operations
    transform_operation: Optional[Literal[
        "split_to_plan",       # Split single item into plan
        "add_items",           # Add epics/stories
        "merge_items",         # Combine items
        "elevate_to_epic",     # Promote item to epic
        "decompose_to_stories",  # Break epic into stories
        "change_scope",        # Switch between SINGLE, EPICS_ONLY, FULL_PLAN
        "remove_items",        # Delete specific items
    ]] = None
    # For DECISION intent (Phase 30) - decision type hints
    decision_type_hint: Optional[Literal[
        "arch",        # Architecture decisions
        "scope",       # Scope/boundary decisions
        "constraint",  # Technical constraints
        "priority",    # Priority/ordering decisions
        "structure",   # Epic/Story decomposition
        "process",     # Process/workflow decisions
    ]] = None
    decision_title_hint: Optional[str] = None  # Extracted title from decision statement
    # Super-mode for user-facing presentation (Phase 31)
    super_mode: Optional["SuperMode"] = None


# =============================================================================
# Intent to SuperMode mapping (Phase 31)
# Maps 13 fine-grained intents to 5 user-facing modes.
# =============================================================================

INTENT_TO_SUPER_MODE: dict[Intent, SuperMode] = {
    # BUILD: "I'm building something"
    Intent.WORKITEM_CREATE: SuperMode.BUILD,
    Intent.DRAFT_REFINE: SuperMode.BUILD,
    Intent.DRAFT_TRANSFORM: SuperMode.BUILD,
    Intent.TICKET: SuperMode.BUILD,  # Deprecated alias
    # OPERATE: "I'm managing Jira"
    Intent.JIRA_COMMAND: SuperMode.OPERATE,
    Intent.CHANGE_REQUEST: SuperMode.OPERATE,
    Intent.SYNC_REQUEST: SuperMode.OPERATE,
    Intent.TICKET_ACTION: SuperMode.OPERATE,
    # DECIDE: "I'm recording a decision"
    Intent.DECISION: SuperMode.DECIDE,
    # THINK: "Help me think"
    Intent.REVIEW: SuperMode.THINK,
    Intent.JIRA_SEARCH: SuperMode.THINK,
    # CHAT: "Just talking"
    Intent.DISCUSSION: SuperMode.CHAT,
    Intent.META: SuperMode.CHAT,
    Intent.AMBIGUOUS: SuperMode.CHAT,
    Intent.OPS: SuperMode.CHAT,  # Ops is meta-level, treat as chat
}


def get_super_mode(intent: Intent) -> SuperMode:
    """Get the user-facing super-mode for a given intent.

    Args:
        intent: The fine-grained intent

    Returns:
        The corresponding SuperMode for user presentation
    """
    return INTENT_TO_SUPER_MODE.get(intent, SuperMode.CHAT)
