"""State schema for the LangGraph agent."""
from enum import Enum
from typing import Literal, Optional, Annotated, Any, TYPE_CHECKING
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from src.schemas.ticket import JiraTicketBase
from src.schemas.draft import TicketDraft

if TYPE_CHECKING:
    from src.skills.ask_user import QuestionSet


class AgentPhase(str, Enum):
    """State machine phases for PM-machine workflow.

    COLLECTING -> VALIDATING -> AWAITING_USER -> READY_TO_CREATE -> CREATED

    Backwards transitions allowed (e.g., AWAITING_USER -> COLLECTING if user provides new info).
    """
    COLLECTING = "collecting"  # Extracting requirements from conversation
    VALIDATING = "validating"  # Checking draft completeness
    AWAITING_USER = "awaiting_user"  # Waiting for user input (ASK/PREVIEW)
    READY_TO_CREATE = "ready_to_create"  # Approved, ready for Jira
    CREATED = "created"  # Ticket created in Jira


class ReviewState(str, Enum):
    """Lifecycle state for review_context."""
    ACTIVE = "active"              # Review just posted, awaiting user response
    CONTINUATION = "continuation"  # User responded, bot continuing discussion
    APPROVED = "approved"          # User approved, ready to post decision to channel
    POSTED = "posted"             # Decision posted to channel, can clear context


class UserIntent(str, Enum):
    """Pure user intent - what the user wants, not workflow state.

    This is separate from workflow events (button clicks, approvals) which
    are handled by PendingAction. UserIntent represents the semantic meaning
    of what the user is asking for.
    """
    TICKET = "ticket"           # Create a Jira ticket
    REVIEW = "review"           # Analysis/feedback without Jira
    DISCUSSION = "discussion"   # Casual greeting, simple question
    META = "meta"               # Questions about the bot itself
    AMBIGUOUS = "ambiguous"     # Unclear intent, triggers scope gate


class PendingAction(str, Enum):
    """What the workflow is waiting for (resumable state).

    This replaces overloaded IntentType values like DECISION_APPROVAL.
    Each value represents a specific workflow state where the system
    is waiting for user input to continue.
    """
    WAITING_APPROVAL = "waiting_approval"           # Draft preview shown, waiting approve/reject
    WAITING_SCOPE_CHOICE = "waiting_scope_choice"   # Scope gate shown, waiting user choice
    WAITING_STORY_EDIT = "waiting_story_edit"       # Multi-ticket preview, waiting story edit
    WAITING_DECISION_EDIT = "waiting_decision_edit" # Decision preview, waiting edit
    WAITING_QUANTITY_CONFIRM = "waiting_quantity_confirm"  # Multi-ticket >3 items, confirm
    WAITING_SIZE_CONFIRM = "waiting_size_confirm"   # Multi-ticket large batch, confirm split


class AgentState(TypedDict):
    """State for the Analyst Agent in LangGraph.

    This state flows through the PM-machine workflow:
    extraction -> validation -> decision -> (loop or complete)

    Enhanced for Phase 5 with:
    - AgentPhase enum for state machine
    - TicketDraft for rich draft with evidence tracking
    - step_count for loop protection (max_steps=10)
    - state_version for race detection
    - validation_report for detailed validation results
    - decision_result for routing decisions
    """

    # Conversation history (LangGraph manages with add_messages reducer)
    messages: Annotated[list[BaseMessage], add_messages]

    # Rich ticket draft with evidence tracking
    draft: Optional[TicketDraft]

    # State machine phase
    phase: AgentPhase

    # Loop protection (max_steps=10)
    step_count: int

    # Race detection
    state_version: int
    last_updated_at: Optional[str]

    # Validation results (from validation node)
    validation_report: dict[str, Any]

    # Decision results (from decision node)
    decision_result: dict[str, Any]

    # Thread context
    thread_ts: Optional[str]  # Slack thread timestamp (session ID)
    channel_id: Optional[str]  # Slack channel

    # Channel context (Phase 8 - Global State)
    channel_context: Optional[dict[str, Any]]  # ChannelContextResult.to_dict()

    # Persona (Phase 9)
    persona: Optional[Literal["pm", "security", "architect"]]  # Current active persona
    persona_lock: bool  # If True, persona is locked for this thread
    persona_reason: Optional[Literal["default", "explicit", "detected"]]  # Why persona was set
    persona_confidence: Optional[float]  # Detection confidence (None for explicit/default)
    persona_changed_at: Optional[str]  # ISO timestamp of last persona change
    persona_message_count: int  # Messages since persona change (for indicator display)

    # Validator findings (Phase 9)
    validator_findings: Optional[dict[str, Any]]  # ValidationFindings.model_dump()

    # Metadata
    user_id: Optional[str]  # Requesting user

    # Question tracking (Phase 6 skills)
    pending_questions: Optional[dict[str, Any]]  # Current unanswered QuestionSet (as dict for TypedDict compat)
    question_history: list[dict[str, Any]]  # Past QuestionSets for re-ask tracking

    # First message tracking (for intro/nudge behavior)
    is_first_message: bool  # True on first interaction, False after

    # Conversation context (Phase 11 - Conversation History)
    # Two-layer context pattern for understanding conversation before @mention:
    # - messages: Last 10-30 raw Slack messages for precision (from raw_buffer or on-demand fetch)
    # - summary: Compressed narrative of older conversation (from rolling summary)
    # This field is populated by handlers BEFORE the graph runs, giving all nodes access.
    conversation_context: Optional[dict[str, Any]]  # Conversation history context
    # Structure: {
    #     "messages": [...],        # Raw Slack messages (list of dicts)
    #     "summary": "...",         # Compressed narrative (str | None)
    #     "last_updated_at": "..."  # ISO datetime string
    # }

    # Intent routing (Phase 13)
    intent_result: Optional[dict[str, Any]]  # IntentResult.model_dump()
    # Structure: {
    #     "intent": "TICKET" | "REVIEW" | "DISCUSSION",
    #     "confidence": 0.0-1.0,
    #     "persona_hint": "pm"|"architect"|"security"|None,
    #     "topic": str|None,
    #     "reasons": ["pattern: ...", "keyword: ..."]
    # }

    # Architecture decision tracking (Phase 14)
    review_context: Optional[dict[str, Any]]  # Saved review for decision extraction
    # Structure: {
    #     "state": ReviewState,            # Lifecycle state (ACTIVE, CONTINUATION, APPROVED, POSTED)
    #     "topic": str,                    # From intent_result.topic
    #     "review_summary": str,           # The review analysis text
    #     "persona": str,                  # Which persona gave the review
    #     "review_timestamp": str,         # ISO timestamp
    #     "thread_ts": str,                # Thread where review happened
    #     "channel_id": str,               # Channel for posting decision
    #     "created_at": float,             # Unix timestamp when review was created
    # }

    # Legacy fields (kept for backwards compatibility during migration)
    missing_info: list[str]  # Deprecated: use validation_report instead
    status: Literal["collecting", "ready_to_sync", "synced"]  # Deprecated: use phase instead
