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

    # Metadata
    user_id: Optional[str]  # Requesting user

    # Question tracking (Phase 6 skills)
    pending_questions: Optional[dict[str, Any]]  # Current unanswered QuestionSet (as dict for TypedDict compat)
    question_history: list[dict[str, Any]]  # Past QuestionSets for re-ask tracking

    # Legacy fields (kept for backwards compatibility during migration)
    missing_info: list[str]  # Deprecated: use validation_report instead
    status: Literal["collecting", "ready_to_sync", "synced"]  # Deprecated: use phase instead
